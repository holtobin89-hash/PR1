"""Рабочее место мастера: назначенные заявки, статусы, запчасти, комментарии."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ACTIVE_STATUSES,
    MASTER_TRANSITIONS,
    ROLE_MASTER,
    STATUS_ISSUED,
    now,
)
from ..db import get_db
from ..deps import csrf_protect, require_roles
from ..models import Part, RequestComment, RequestPart, User
from ..repository import get_request, list_requests
from ..templating import render
from ..utils import (
    apply_status_change,
    can_transition,
    flash_redirect,
    parse_money,
    parse_positive_int,
    recalculate_totals,
)

router = APIRouter(
    prefix="/master",
    dependencies=[Depends(csrf_protect), Depends(require_roles(ROLE_MASTER))],
)


def _load_assigned(db: Session, request_id: int, user: User):
    repair_request = get_request(db, request_id)
    if repair_request is None or repair_request.master_id != user.id:
        return None
    return repair_request


def _not_found(request: Request):
    return render(
        request,
        "errors/404.html",
        {"message": "Заявка не найдена или не назначена вам."},
        status_code=404,
    )


@router.get("")
def queue(
    request: Request,
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    active = list_requests(db, master_id=user.id, statuses=ACTIVE_STATUSES)
    history = list_requests(
        db, master_id=user.id, statuses=[STATUS_ISSUED, "cancelled"], limit=20
    )
    counters = {
        "active": len(active),
        "new": sum(1 for item in active if item.status == "accepted"),
        "in_repair": sum(1 for item in active if item.status == "in_repair"),
        "ready": sum(1 for item in active if item.status == "ready"),
    }
    return render(
        request,
        "master/queue.html",
        {
            "active": "queue",
            "requests": active,
            "history": history,
            "counters": counters,
        },
    )


@router.get("/requests/{request_id}")
def request_detail(
    request_id: int,
    request: Request,
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    parts = list(
        db.scalars(
            select(Part)
            .where(Part.is_active.is_(True), Part.quantity > 0)
            .order_by(Part.name)
        ).all()
    )
    return render(
        request,
        "master/request.html",
        {
            "r": repair_request,
            "available_parts": parts,
            "transitions": MASTER_TRANSITIONS.get(repair_request.status, []),
            "active": "queue",
        },
    )


@router.post("/requests/{request_id}/status")
def change_status(
    request_id: int,
    request: Request,
    status: str = Form(""),
    comment: str = Form(""),
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    if status not in MASTER_TRANSITIONS.get(repair_request.status, []):
        return flash_redirect(
            f"/master/requests/{request_id}",
            "Этот переход статуса недоступен. Обновите страницу.",
            "error",
        )
    if not can_transition(repair_request.status, status, user.role):
        return flash_redirect(
            f"/master/requests/{request_id}", "Недопустимый переход статуса.", "error"
        )
    apply_status_change(repair_request, status, comment.strip() or None, user.id, user.role)
    db.commit()
    return flash_redirect(
        f"/master/requests/{request_id}", "Статус заявки обновлён."
    )


@router.post("/requests/{request_id}/comment")
def add_comment(
    request_id: int,
    request: Request,
    body: str = Form(""),
    is_internal: str = Form(""),
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    body = body.strip()
    if not body:
        return flash_redirect(
            f"/master/requests/{request_id}", "Комментарий не может быть пустым.", "error"
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
    return flash_redirect(f"/master/requests/{request_id}", "Комментарий добавлен.")


@router.post("/requests/{request_id}/parts")
def add_part(
    request_id: int,
    request: Request,
    part_id: str = Form(""),
    quantity: str = Form("1"),
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    if repair_request.status in (STATUS_ISSUED, "cancelled"):
        return flash_redirect(
            f"/master/requests/{request_id}",
            "Нельзя менять запчасти в закрытой заявке.",
            "error",
        )
    part_id_value = parse_positive_int(part_id)
    quantity_value = parse_positive_int(quantity)
    part = db.get(Part, part_id_value) if part_id_value else None
    if part is None or not part.is_active:
        return flash_redirect(
            f"/master/requests/{request_id}", "Выберите запчасть из списка.", "error"
        )
    if quantity_value is None:
        return flash_redirect(
            f"/master/requests/{request_id}", "Количество должно быть больше нуля.", "error"
        )

    usage = db.scalar(
        select(RequestPart).where(
            RequestPart.request_id == repair_request.id,
            RequestPart.part_id == part.id,
        )
    )
    if part.quantity < quantity_value:
        return flash_redirect(
            f"/master/requests/{request_id}",
            f"На складе недостаточно деталей «{part.name}»: остаток {part.quantity} {part.unit}.",
            "error",
        )

    part.quantity -= quantity_value
    if usage:
        usage.quantity += quantity_value
    else:
        repair_request.parts.append(
            RequestPart(
                part_id=part.id,
                quantity=quantity_value,
                unit_price=part.price,
                created_at=now(),
            )
        )
    recalculate_totals(repair_request)
    repair_request.updated_at = now()
    db.commit()
    return flash_redirect(
        f"/master/requests/{request_id}",
        f"Списано со склада: {part.name} × {quantity_value}.",
    )


@router.post("/requests/{request_id}/parts/{usage_id}/delete")
def remove_part(
    request_id: int,
    usage_id: int,
    request: Request,
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    usage = db.get(RequestPart, usage_id)
    if usage is None or usage.request_id != repair_request.id:
        return _not_found(request)
    if repair_request.status in (STATUS_ISSUED, "cancelled"):
        return flash_redirect(
            f"/master/requests/{request_id}",
            "Нельзя менять запчасти в закрытой заявке.",
            "error",
        )
    usage.part.quantity += usage.quantity
    repair_request.parts.remove(usage)
    db.delete(usage)
    recalculate_totals(repair_request)
    repair_request.updated_at = now()
    db.commit()
    return flash_redirect(
        f"/master/requests/{request_id}", "Запчасть возвращена на склад."
    )


@router.post("/requests/{request_id}/cost")
def update_cost(
    request_id: int,
    request: Request,
    labor_cost: str = Form(""),
    user: User = Depends(require_roles(ROLE_MASTER)),
    db: Session = Depends(get_db),
):
    repair_request = _load_assigned(db, request_id, user)
    if repair_request is None:
        return _not_found(request)
    value = parse_money(labor_cost)
    if value is None:
        return flash_redirect(
            f"/master/requests/{request_id}", "Укажите корректную стоимость работ.", "error"
        )
    repair_request.labor_cost = value
    recalculate_totals(repair_request)
    repair_request.updated_at = now()
    db.commit()
    return flash_redirect(f"/master/requests/{request_id}", "Стоимость работ обновлена.")