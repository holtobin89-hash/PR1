"""Личный кабинет клиента: заявки, история, создание обращения."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ..constants import (
    ACTIVE_STATUSES,
    DEVICE_TYPES,
    ROLE_CLIENT,
    STATUS_ACCEPTED,
    STATUS_ISSUED,
    STATUS_READY,
    now,
)
from ..db import get_db
from ..deps import csrf_protect, require_roles
from ..models import RepairRequest, RequestStatusLog, Service, User
from ..repository import active_services, get_request, list_requests
from ..templating import render
from ..utils import (
    apply_status_change,
    can_transition,
    flash_redirect,
    generate_request_number,
    parse_positive_int,
    save_upload,
)

router = APIRouter(
    prefix="/client",
    dependencies=[Depends(csrf_protect), Depends(require_roles(ROLE_CLIENT))],
)


@router.get("")
def dashboard(request: Request, user: User = Depends(require_roles(ROLE_CLIENT)), db: Session = Depends(get_db)):
    requests = list_requests(db, client_id=user.id)
    counters = {
        "total": len(requests),
        "active": sum(1 for item in requests if item.status in ACTIVE_STATUSES),
        "ready": sum(1 for item in requests if item.status == STATUS_READY),
        "done": sum(1 for item in requests if item.status == STATUS_ISSUED),
    }
    return render(
        request,
        "client/dashboard.html",
        {"requests": requests, "counters": counters, "active": "dashboard"},
    )


@router.get("/requests/new")
def new_request_page(
    request: Request,
    service_id: int | None = None,
    user: User = Depends(require_roles(ROLE_CLIENT)),
    db: Session = Depends(get_db),
):
    services = active_services(db)
    return render(
        request,
        "client/new_request.html",
        {
            "services": services,
            "device_types": DEVICE_TYPES,
            "selected_service": service_id,
            "form": {},
            "active": "new",
        },
    )


@router.post("/requests/new")
def create_request(
    request: Request,
    device_type: str = Form(""),
    brand_model: str = Form(""),
    serial_number: str = Form(""),
    description: str = Form(""),
    service_id: str = Form(""),
    photo: UploadFile | None = File(None),
    user: User = Depends(require_roles(ROLE_CLIENT)),
    db: Session = Depends(get_db),
):
    form = {
        "device_type": device_type.strip(),
        "brand_model": brand_model.strip(),
        "serial_number": serial_number.strip(),
        "description": description.strip(),
        "service_id": service_id.strip(),
    }
    errors: list[str] = []

    if form["device_type"] not in DEVICE_TYPES:
        errors.append("Выберите тип устройства из списка.")
    if len(form["brand_model"]) > 150:
        errors.append("Модель устройства слишком длинная.")
    if len(form["description"]) < 10:
        errors.append("Опишите неисправность подробнее (минимум 10 символов).")
    if len(form["description"]) > 4000:
        errors.append("Описание не должно превышать 4000 символов.")

    service: Service | None = None
    service_id_value = parse_positive_int(form["service_id"])
    if service_id_value:
        service = db.get(Service, service_id_value)
        if service is None or not service.is_active:
            errors.append("Выбранная услуга недоступна.")

    photo_path = None
    try:
        photo_path = save_upload(photo)
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        services = active_services(db)
        return render(
            request,
            "client/new_request.html",
            {
                "services": services,
                "device_types": DEVICE_TYPES,
                "form": form,
                "errors": errors,
                "selected_service": service_id_value,
                "active": "new",
            },
            status_code=400,
        )

    repair_request = RepairRequest(
        number=generate_request_number(db),
        client_id=user.id,
        service_id=service.id if service else None,
        device_type=form["device_type"],
        brand_model=form["brand_model"] or None,
        serial_number=form["serial_number"] or None,
        description=form["description"],
        photo_path=photo_path,
        status=STATUS_ACCEPTED,
        created_at=now(),
    )
    repair_request.status_logs.append(
        RequestStatusLog(
            status=STATUS_ACCEPTED,
            comment="Заявка создана клиентом.",
            user_id=user.id,
            created_at=now(),
        )
    )
    db.add(repair_request)
    db.commit()

    return flash_redirect(
        f"/client/requests/{repair_request.id}",
        f"Заявка {repair_request.number} принята. Мы свяжемся с вами для уточнения деталей.",
    )


@router.get("/requests/{request_id}")
def request_detail(
    request_id: int,
    request: Request,
    user: User = Depends(require_roles(ROLE_CLIENT)),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None or repair_request.client_id != user.id:
        return render(request, "errors/404.html", {"message": "Заявка не найдена."}, status_code=404)
    return render(
        request,
        "client/request.html",
        {"r": repair_request, "active": "dashboard"},
    )


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    request_id: int,
    request: Request,
    comment: str = Form(""),
    user: User = Depends(require_roles(ROLE_CLIENT)),
    db: Session = Depends(get_db),
):
    repair_request = get_request(db, request_id)
    if repair_request is None or repair_request.client_id != user.id:
        return render(request, "errors/404.html", {"message": "Заявка не найдена."}, status_code=404)
    target = "cancelled"
    if not can_transition(repair_request.status, target, user.role):
        return flash_redirect(
            f"/client/requests/{request_id}",
            "Отменить можно только заявку в статусе «Принята». Свяжитесь с мастерской.",
            "error",
        )
    apply_status_change(
        repair_request,
        target,
        comment.strip() or "Заявка отменена клиентом.",
        user.id,
        user.role,
    )
    db.commit()
    return flash_redirect(f"/client/requests/{request_id}", "Заявка отменена.", "info")