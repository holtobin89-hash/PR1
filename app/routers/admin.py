"""Панель администратора: заявки, услуги, склад, сотрудники, статистика."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    ROLE_LABELS,
    STATUS_ISSUED,
    STATUS_READY,
    now,
)
from ..db import get_db
from ..deps import csrf_protect, require_roles
from ..models import Part, RepairRequest, RequestComment, Service, User
from ..repository import active_masters, get_request, list_requests
from ..templating import render
from ..utils import (
    apply_status_change,
    can_transition,
    flash_redirect,
    is_valid_email,
    is_valid_phone,
    normalize_email,
    parse_money,
    parse_positive_int,
    validate_password,
)
from ..security import hash_password

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(csrf_protect), Depends(require_roles("admin"))],
)


# --------------------------------------------------------------------------- #
# Дашборд
# --------------------------------------------------------------------------- #
@router.get("")
def dashboard(
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    requests = list_requests(db, limit=8)
    active_count = db.scalar(
        select(func.count(RepairRequest.id)).where(
            RepairRequest.status.in_(ACTIVE_STATUSES)
        )
    ) or 0
    counters = {
        "active": active_count,
        "unassigned": db.scalar(
            select(func.count(RepairRequest.id)).where(
                RepairRequest.status.in_(ACTIVE_STATUSES),
                RepairRequest.master_id.is_(None),
            )
        )
        or 0,
        "ready": db.scalar(
            select(func.count(RepairRequest.id)).where(
                RepairRequest.status == STATUS_READY
            )
        )
        or 0,
        "masters": len(active_masters(db)),
        "clients": db.scalar(
            select(func.count(User.id)).where(User.role == "client")
        )
        or 0,
        "low_stock": db.scalar(
            select(func.count(Part.id)).where(
                Part.is_active.is_(True), Part.quantity <= Part.min_quantity
            )
        )
        or 0,
    }
    return render(
        request,
        "admin/dashboard.html",
        {"requests": requests, "counters": counters, "active": "dashboard"},
    )


# --------------------------------------------------------------------------- #
# Заявки
# --------------------------------------------------------------------------- #
@router.get("/requests")
def requests_list(
    request: Request,
    status: str = "",
    master_id: str = "",
    q: str = "",
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    statuses = [status] if status in ALL_STATUSES else None
    master_id_value = parse_positive_int(master_id)
    requests = list_requests(
        db,
        statuses=statuses,
        master_id=master_id_value,
        search=q or None,
    )
    return render(
        request,
        "admin/requests.html",
        {
            "requests": requests,
            "masters": active_masters(db),
            "filters": {
                "status": status,
                "master_id": master_id_value,
                "q": q,
            },
            "active": "requests",
        },
    )


@router.get("/requests/{request_id}")
def request_detail(
    request_id: int,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Заявка не найдена."},
            status_code=404,
        )
    return render(
        request,
        "admin/request.html",
        {
            "r": repair_request,
            "masters": active_masters(db),
            "all_statuses": ALL_STATUSES,
            "active": "requests",
        },
    )


@router.post("/requests/{request_id}/assign")
def assign_master(
    request_id: int,
    request: Request,
    master_id: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Заявка не найдена."},
            status_code=404,
        )
    if not master_id:
        repair_request.master_id = None
        repair_request.updated_at = now()
        db.commit()
        return flash_redirect(
            f"/admin/requests/{request_id}", "Мастер снят с заявки.", "info"
        )
    master = db.get(User, parse_positive_int(master_id) or 0)
    if master is None or master.role != "master" or not master.is_active:
        return flash_redirect(
            f"/admin/requests/{request_id}", "Выберите активного мастера.", "error"
        )
    repair_request.master_id = master.id
    repair_request.updated_at = now()
    db.commit()
    return flash_redirect(
        f"/admin/requests/{request_id}", f"Заявка назначена мастеру {master.full_name}."
    )


@router.post("/requests/{request_id}/status")
def change_status(
    request_id: int,
    request: Request,
    status: str = Form(""),
    comment: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Заявка не найдена."},
            status_code=404,
        )
    if status not in ALL_STATUSES or not can_transition(
        repair_request.status, status, user.role
    ):
        return flash_redirect(
            f"/admin/requests/{request_id}", "Недопустимый статус.", "error"
        )
    apply_status_change(repair_request, status, comment.strip() or None, user.id, user.role)
    db.commit()
    return flash_redirect(
        f"/admin/requests/{request_id}", "Статус заявки обновлён."
    )


@router.post("/requests/{request_id}/comment")
def add_comment(
    request_id: int,
    request: Request,
    body: str = Form(""),
    is_internal: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Заявка не найдена."},
            status_code=404,
        )
    body = body.strip()
    if not body:
        return flash_redirect(
            f"/admin/requests/{request_id}", "Комментарий не может быть пустым.", "error"
        )
    repair_request.comments.append(
        RequestComment(
            author_id=user.id,
            body=body[:4000],
            is_internal=bool(is_internal),
            created_at=now(),
        )
    )
    repair_request.updated_at = now()
    db.commit()
    return flash_redirect(
        f"/admin/requests/{request_id}", "Комментарий добавлен."
    )


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #
@router.get("/services")
def services_list(
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    services = list(
        db.scalars(select(Service).order_by(Service.category, Service.name)).all()
    )
    return render(
        request,
        "admin/services.html",
        {"services": services, "active": "services"},
    )


@router.get("/services/new")
def service_new_page(
    request: Request, user: User = Depends(require_roles("admin"))
):
    return render(
        request,
        "admin/service_form.html",
        {"service": None, "form": {}, "active": "services"},
    )


@router.post("/services/new")
def service_create(
    request: Request,
    name: str = Form(""),
    category: str = Form(""),
    description: str = Form(""),
    price_from: str = Form("0"),
    duration_days: str = Form("1"),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    form = {
        "name": name.strip(),
        "category": category.strip() or "Прочее",
        "description": description.strip(),
        "price_from": price_from,
        "duration_days": duration_days,
    }
    errors = _validate_service_form(form)
    if errors:
        return render(
            request,
            "admin/service_form.html",
            {"service": None, "form": form, "errors": errors, "active": "services"},
            status_code=400,
        )
    service = Service(
        name=form["name"],
        category=form["category"],
        description=form["description"] or None,
        price_from=parse_money(form["price_from"]),
        duration_days=parse_positive_int(form["duration_days"]) or 1,
    )
    db.add(service)
    db.commit()
    return flash_redirect("/admin/services", "Услуга добавлена в каталог.")


@router.get("/services/{service_id}/edit")
def service_edit_page(
    service_id: int,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    service = db.get(Service, service_id)
    if service is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Услуга не найдена."},
            status_code=404,
        )
    return render(
        request,
        "admin/service_form.html",
        {"service": service, "form": {}, "active": "services"},
    )


@router.post("/services/{service_id}/edit")
def service_update(
    service_id: int,
    request: Request,
    name: str = Form(""),
    category: str = Form(""),
    description: str = Form(""),
    price_from: str = Form("0"),
    duration_days: str = Form("1"),
    is_active: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    service = db.get(Service, service_id)
    if service is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Услуга не найдена."},
            status_code=404,
        )
    form = {
        "name": name.strip(),
        "category": category.strip() or "Прочее",
        "description": description.strip(),
        "price_from": price_from,
        "duration_days": duration_days,
        "is_active": bool(is_active),
    }
    errors = _validate_service_form(form)
    if errors:
        return render(
            request,
            "admin/service_form.html",
            {"service": service, "form": form, "errors": errors, "active": "services"},
            status_code=400,
        )
    service.name = form["name"]
    service.category = form["category"]
    service.description = form["description"] or None
    service.price_from = parse_money(form["price_from"])
    service.duration_days = parse_positive_int(form["duration_days"]) or 1
    service.is_active = form["is_active"]
    db.commit()
    return flash_redirect("/admin/services", "Услуга обновлена.")


def _validate_service_form(form: dict) -> list[str]:
    errors: list[str] = []
    if len(form["name"]) < 3:
        errors.append("Название услуги должно содержать минимум 3 символа.")
    if len(form["name"]) > 150:
        errors.append("Название услуги слишком длинное.")
    if parse_money(form["price_from"]) is None:
        errors.append("Укажите корректную цену (число не больше 99 999 999).")
    if parse_positive_int(form["duration_days"]) is None:
        errors.append("Срок выполнения — целое число дней, не меньше 1.")
    return errors


# --------------------------------------------------------------------------- #
# Склад
# --------------------------------------------------------------------------- #
@router.get("/parts")
def parts_list(
    request: Request,
    q: str = "",
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    statement = select(Part).order_by(Part.name)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            Part.name.ilike(pattern) | Part.sku.ilike(pattern)
        )
    parts = list(db.scalars(statement).all())
    low_stock = [part for part in parts if part.is_active and part.is_low_stock]
    return render(
        request,
        "admin/parts.html",
        {"parts": parts, "low_stock": low_stock, "query": q, "active": "parts"},
    )


@router.get("/parts/new")
def part_new_page(request: Request, user: User = Depends(require_roles("admin"))):
    return render(
        request,
        "admin/part_form.html",
        {"part": None, "form": {}, "active": "parts"},
    )


@router.post("/parts/new")
def part_create(
    request: Request,
    sku: str = Form(""),
    name: str = Form(""),
    unit: str = Form("шт."),
    quantity: str = Form("0"),
    min_quantity: str = Form("0"),
    price: str = Form("0"),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    form = {
        "sku": sku.strip().upper(),
        "name": name.strip(),
        "unit": unit.strip() or "шт.",
        "quantity": quantity,
        "min_quantity": min_quantity,
        "price": price,
    }
    errors = _validate_part_form(form)
    if not errors and db.scalar(select(Part).where(Part.sku == form["sku"])):
        errors.append("Запчасть с таким артикулом уже существует.")
    if errors:
        return render(
            request,
            "admin/part_form.html",
            {"part": None, "form": form, "errors": errors, "active": "parts"},
            status_code=400,
        )
    part = Part(
        sku=form["sku"],
        name=form["name"],
        unit=form["unit"],
        quantity=int(form["quantity"]),
        min_quantity=int(form["min_quantity"]),
        price=parse_money(form["price"]),
    )
    db.add(part)
    db.commit()
    return flash_redirect("/admin/parts", "Запчасть добавлена на склад.")


@router.get("/parts/{part_id}/edit")
def part_edit_page(
    part_id: int,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    part = db.get(Part, part_id)
    if part is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Запчасть не найдена."},
            status_code=404,
        )
    return render(
        request,
        "admin/part_form.html",
        {"part": part, "form": {}, "active": "parts"},
    )


@router.post("/parts/{part_id}/edit")
def part_update(
    part_id: int,
    request: Request,
    sku: str = Form(""),
    name: str = Form(""),
    unit: str = Form("шт."),
    min_quantity: str = Form("0"),
    price: str = Form("0"),
    is_active: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    part = db.get(Part, part_id)
    if part is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Запчасть не найдена."},
            status_code=404,
        )
    form = {
        "sku": sku.strip().upper(),
        "name": name.strip(),
        "unit": unit.strip() or "шт.",
        "quantity": part.quantity,
        "min_quantity": min_quantity,
        "price": price,
        "is_active": bool(is_active),
    }
    errors = _validate_part_form(form)
    duplicate = db.scalar(
        select(Part).where(Part.sku == form["sku"], Part.id != part.id)
    )
    if duplicate:
        errors.append("Запчасть с таким артикулом уже существует.")
    if errors:
        return render(
            request,
            "admin/part_form.html",
            {"part": part, "form": form, "errors": errors, "active": "parts"},
            status_code=400,
        )
    part.sku = form["sku"]
    part.name = form["name"]
    part.unit = form["unit"]
    part.min_quantity = int(form["min_quantity"])
    part.price = parse_money(form["price"])
    part.is_active = form["is_active"]
    db.commit()
    return flash_redirect("/admin/parts", "Данные запчасти обновлены.")


def _validate_part_form(form: dict) -> list[str]:
    errors: list[str] = []
    if len(form["sku"]) < 2:
        errors.append("Артикул должен содержать минимум 2 символа.")
    if len(form["name"]) < 2:
        errors.append("Укажите наименование запчасти.")
    if parse_money(form["price"]) is None:
        errors.append("Укажите корректную цену.")
    for field, label in (("quantity", "Количество"), ("min_quantity", "Минимум")):
        value = form.get(field)
        try:
            if int(value) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{label} — целое неотрицательное число.")
    return errors


@router.post("/parts/{part_id}/stock")
def part_stock(
    part_id: int,
    request: Request,
    amount: str = Form(""),
    comment: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    part = db.get(Part, part_id)
    if part is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Запчасть не найдена."},
            status_code=404,
        )
    try:
        delta = int((amount or "").strip())
    except ValueError:
        return flash_redirect(
            "/admin/parts", "Введите целое число: приход со знаком «+», списание — «−»."
        )
    if delta == 0:
        return flash_redirect("/admin/parts", "Количество не изменилось.", "info")
    if part.quantity + delta < 0:
        return flash_redirect(
            "/admin/parts",
            f"Нельзя списать больше остатка ({part.quantity} {part.unit}).",
            "error",
        )
    part.quantity += delta
    part.updated_at = now()
    db.commit()
    action = "Приход" if delta > 0 else "Списание"
    return flash_redirect(
        "/admin/parts",
        f"{action}: {abs(delta)} {part.unit} «{part.name}». Остаток: {part.quantity}.",
    )


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
@router.get("/users")
def users_list(
    request: Request,
    role: str = "",
    q: str = "",
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    statement = select(User).order_by(User.role, User.full_name)
    if role in ROLE_LABELS:
        statement = statement.where(User.role == role)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            User.full_name.ilike(pattern)
            | User.email.ilike(pattern)
            | User.phone.ilike(pattern)
        )
    users = list(db.scalars(statement).all())
    return render(
        request,
        "admin/users.html",
        {
            "users": users,
            "filters": {"role": role, "q": q},
            "active": "users",
        },
    )


@router.get("/users/new")
def user_new_page(request: Request, user: User = Depends(require_roles("admin"))):
    return render(
        request,
        "admin/user_form.html",
        {"edited_user": None, "form": {}, "roles": ROLE_LABELS, "active": "users"},
    )


@router.post("/users/new")
def user_create(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    role: str = Form("master"),
    password: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    form = {
        "full_name": full_name.strip(),
        "email": normalize_email(email),
        "phone": phone.strip(),
        "role": role,
    }
    errors = _validate_user_form(form, password, check_password=True)
    if not errors and db.scalar(select(User).where(User.email == form["email"])):
        errors.append("Пользователь с таким e-mail уже существует.")
    if errors:
        return render(
            request,
            "admin/user_form.html",
            {
                "edited_user": None,
                "form": form,
                "errors": errors,
                "roles": ROLE_LABELS,
                "active": "users",
            },
            status_code=400,
        )
    new_user = User(
        full_name=form["full_name"],
        email=form["email"],
        phone=form["phone"] or None,
        role=form["role"],
        password_hash=hash_password(password),
    )
    db.add(new_user)
    db.commit()
    return flash_redirect("/admin/users", "Пользователь создан.")


@router.get("/users/{user_id}/edit")
def user_edit_page(
    user_id: int,
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    edited_user = db.get(User, user_id)
    if edited_user is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Пользователь не найден."},
            status_code=404,
        )
    return render(
        request,
        "admin/user_form.html",
        {
            "edited_user": edited_user,
            "form": {},
            "roles": ROLE_LABELS,
            "active": "users",
        },
    )


@router.post("/users/{user_id}/edit")
def user_update(
    user_id: int,
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    role: str = Form("client"),
    password: str = Form(""),
    is_active: str = Form(""),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    edited_user = db.get(User, user_id)
    if edited_user is None:
        return render(
            request,
            "errors/404.html",
            {"message": "Пользователь не найден."},
            status_code=404,
        )
    form = {
        "full_name": full_name.strip(),
        "email": normalize_email(email),
        "phone": phone.strip(),
        "role": role,
        "is_active": bool(is_active),
    }
    errors = _validate_user_form(form, password, check_password=False)
    duplicate = db.scalar(
        select(User).where(User.email == form["email"], User.id != edited_user.id)
    )
    if duplicate:
        errors.append("Пользователь с таким e-mail уже существует.")
    if edited_user.id == user.id and not form["is_active"]:
        errors.append("Нельзя заблокировать собственную учётную запись.")
    if edited_user.id == user.id and form["role"] != "admin":
        errors.append("Нельзя снять с себя роль администратора.")
    if errors:
        return render(
            request,
            "admin/user_form.html",
            {
                "edited_user": edited_user,
                "form": form,
                "errors": errors,
                "roles": ROLE_LABELS,
                "active": "users",
            },
            status_code=400,
        )
    edited_user.full_name = form["full_name"]
    edited_user.email = form["email"]
    edited_user.phone = form["phone"] or None
    edited_user.role = form["role"]
    edited_user.is_active = form["is_active"]
    if password:
        edited_user.password_hash = hash_password(password)
    db.commit()
    return flash_redirect("/admin/users", "Данные пользователя обновлены.")


def _validate_user_form(form: dict, password: str, check_password: bool) -> list[str]:
    errors: list[str] = []
    if len(form["full_name"]) < 2:
        errors.append("Укажите ФИО пользователя.")
    if not is_valid_email(form["email"]):
        errors.append("Введите корректный e-mail.")
    if not is_valid_phone(form["phone"]):
        errors.append("Телефон должен содержать 7–30 цифр и символов + ( ) -.")
    if form["role"] not in ROLE_LABELS:
        errors.append("Выберите роль из списка.")
    if check_password:
        password_error = validate_password(password)
        if password_error:
            errors.append(password_error)
    elif password:
        password_error = validate_password(password)
        if password_error:
            errors.append(password_error)
    return errors


# --------------------------------------------------------------------------- #
# Статистика
# --------------------------------------------------------------------------- #
@router.get("/stats")
def stats(
    request: Request,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    today = date.today()
    start_day = today - timedelta(days=13)
    rows = db.execute(
        select(
            func.date(RepairRequest.created_at).label("day"),
            func.count(RepairRequest.id),
        )
        .where(func.date(RepairRequest.created_at) >= start_day.isoformat())
        .group_by("day")
    ).all()
    counts_by_day = {str(day): count for day, count in rows}

    day_labels = [(start_day + timedelta(days=offset)) for offset in range(14)]
    requests_chart = {
        "labels": [day.strftime("%d.%m") for day in day_labels],
        "values": [counts_by_day.get(day.isoformat(), 0) for day in day_labels],
    }

    # Выручка по месяцам за последние 6 месяцев (только выданные заявки).
    first_month = (today.replace(day=1) - timedelta(days=155)).replace(day=1)
    revenue_rows = db.execute(
        select(
            func.strftime("%Y-%m", RepairRequest.completed_at).label("month"),
            func.coalesce(func.sum(RepairRequest.total_cost), 0),
        )
        .where(
            RepairRequest.status == STATUS_ISSUED,
            RepairRequest.completed_at.is_not(None),
            func.date(RepairRequest.completed_at) >= first_month.isoformat(),
        )
        .group_by("month")
        .order_by("month")
    ).all()
    revenue_map = {month: float(total) for month, total in revenue_rows}

    months: list[date] = []
    cursor = first_month
    while cursor <= today:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    month_names = [
        "янв", "фев", "мар", "апр", "май", "июн",
        "июл", "авг", "сен", "окт", "ноя", "дек",
    ]
    revenue_chart = {
        "labels": [f"{month_names[month.month - 1]} {month.year}" for month in months],
        "values": [round(revenue_map.get(month.strftime("%Y-%m"), 0), 2) for month in months],
    }

    device_rows = db.execute(
        select(RepairRequest.device_type, func.count(RepairRequest.id))
        .group_by(RepairRequest.device_type)
        .order_by(func.count(RepairRequest.id).desc())
        .limit(6)
    ).all()
    device_chart = {
        "labels": [row[0] for row in device_rows],
        "values": [row[1] for row in device_rows],
    }

    load_rows = db.execute(
        select(User.full_name, func.count(RepairRequest.id))
        .join(RepairRequest, RepairRequest.master_id == User.id)
        .where(RepairRequest.status.in_(ACTIVE_STATUSES))
        .group_by(User.id)
        .order_by(func.count(RepairRequest.id).desc())
    ).all()
    load_chart = {
        "labels": [row[0] for row in load_rows],
        "values": [row[1] for row in load_rows],
    }

    total_revenue = db.scalar(
        select(func.coalesce(func.sum(RepairRequest.total_cost), 0)).where(
            RepairRequest.status == STATUS_ISSUED
        )
    ) or 0
    month_revenue = db.scalar(
        select(func.coalesce(func.sum(RepairRequest.total_cost), 0)).where(
            RepairRequest.status == STATUS_ISSUED,
            func.strftime("%Y-%m", RepairRequest.completed_at) == today.strftime("%Y-%m"),
        )
    ) or 0
    avg_check = db.scalar(
        select(func.coalesce(func.avg(RepairRequest.total_cost), 0)).where(
            RepairRequest.status == STATUS_ISSUED
        )
    ) or 0
    by_status = {
        status: db.scalar(
            select(func.count(RepairRequest.id)).where(RepairRequest.status == status)
        )
        or 0
        for status in ALL_STATUSES
    }

    return render(
        request,
        "admin/stats.html",
        {
            "active": "stats",
            "requests_chart": requests_chart,
            "revenue_chart": revenue_chart,
            "device_chart": device_chart,
            "load_chart": load_chart,
            "indicators": {
                "total_revenue": total_revenue,
                "month_revenue": month_revenue,
                "avg_check": avg_check,
                "total_requests": sum(by_status.values()),
            },
            "by_status": by_status,
        },
    )