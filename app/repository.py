"""Запросы к БД, используемые несколькими роутерами."""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from .models import (
    RepairRequest,
    RequestComment,
    RequestPart,
    RequestStatusLog,
    Service,
    User,
)


def get_request(db: Session, request_id: int) -> RepairRequest | None:
    """Заявка со всеми связями, нужными для карточки."""
    return db.scalar(
        select(RepairRequest)
        .where(RepairRequest.id == request_id)
        .options(
            joinedload(RepairRequest.client),
            joinedload(RepairRequest.master),
            joinedload(RepairRequest.service),
            selectinload(RepairRequest.status_logs).joinedload(RequestStatusLog.user),
            selectinload(RepairRequest.comments).joinedload(RequestComment.author),
            selectinload(RepairRequest.parts).joinedload(RequestPart.part),
        )
    )


def list_requests(
    db: Session,
    client_id: int | None = None,
    master_id: int | None = None,
    statuses: list[str] | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[RepairRequest]:
    statement = select(RepairRequest).options(
        joinedload(RepairRequest.client),
        joinedload(RepairRequest.master),
        joinedload(RepairRequest.service),
        selectinload(RepairRequest.parts),
    )
    if client_id is not None:
        statement = statement.where(RepairRequest.client_id == client_id)
    if master_id is not None:
        statement = statement.where(RepairRequest.master_id == master_id)
    if statuses:
        statement = statement.where(RepairRequest.status.in_(statuses))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.join(RepairRequest.client).where(
            RepairRequest.number.ilike(pattern)
            | RepairRequest.device_type.ilike(pattern)
            | RepairRequest.brand_model.ilike(pattern)
            | User.full_name.ilike(pattern)
            | User.phone.ilike(pattern)
        )
    statement = statement.order_by(RepairRequest.created_at.desc()).limit(limit)
    return list(db.scalars(statement).unique().all())


def active_services(db: Session) -> list[Service]:
    return list(
        db.scalars(
            select(Service)
            .where(Service.is_active.is_(True))
            .order_by(Service.category, Service.name)
        ).all()
    )


def active_masters(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.role == "master", User.is_active.is_(True))
            .order_by(User.full_name)
        ).all()
    )