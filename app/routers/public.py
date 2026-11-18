"""Публичные страницы: главная и каталог услуг."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..constants import ACTIVE_STATUSES, ROLE_MASTER, STATUS_ISSUED
from ..db import get_db
from ..deps import get_current_user
from ..models import RepairRequest, Service, User
from ..templating import render

router = APIRouter(dependencies=[Depends(get_current_user)])


def _catalog_context(db: Session, query: str = "", category: str = ""):
    statement = select(Service).where(Service.is_active.is_(True))
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(Service.name.ilike(pattern), Service.description.ilike(pattern))
        )
    if category:
        statement = statement.where(Service.category == category)
    services = db.scalars(
        statement.order_by(Service.category, Service.price_from)
    ).all()

    grouped: dict[str, list[Service]] = {}
    for service in services:
        grouped.setdefault(service.category, []).append(service)

    categories = db.scalars(
        select(Service.category)
        .where(Service.is_active.is_(True))
        .distinct()
        .order_by(Service.category)
    ).all()
    return grouped, categories


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    grouped, _ = _catalog_context(db)
    services = [service for items in grouped.values() for service in items]
    stats = {
        "services": len(services),
        "masters": db.scalar(
            select(func.count(User.id)).where(
                User.role == ROLE_MASTER, User.is_active.is_(True)
            )
        )
        or 0,
        "in_work": db.scalar(
            select(func.count(RepairRequest.id)).where(
                RepairRequest.status.in_(ACTIVE_STATUSES)
            )
        )
        or 0,
        "completed": db.scalar(
            select(func.count(RepairRequest.id)).where(
                RepairRequest.status == STATUS_ISSUED
            )
        )
        or 0,
    }
    return render(
        request,
        "index.html",
        {"services": services[:6], "stats": stats, "active": "home"},
    )


@router.get("/catalog")
def catalog(
    request: Request,
    q: str = "",
    category: str = "",
    db: Session = Depends(get_db),
):
    grouped, categories = _catalog_context(db, q, category)
    total = sum(len(items) for items in grouped.values())
    return render(
        request,
        "catalog.html",
        {
            "grouped": grouped,
            "categories": categories,
            "query": q,
            "selected_category": category,
            "total": total,
            "active": "catalog",
        },
    )


@router.get("/health")
def health():
    return {"status": "ok"}