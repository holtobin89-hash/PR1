"""Валидация данных, работа с заявками, загрузка фото, flash-сообщения."""
import base64
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_UPLOAD_SIZE,
    UPLOAD_DIR,
)
from .constants import (
    MASTER_TRANSITIONS,
    ROLE_ADMIN,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_ISSUED,
    now,
)
from .models import RepairRequest, RequestStatusLog

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,30}$")

IMAGE_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value or ""))


def is_valid_phone(value: str) -> bool:
    return not value or bool(PHONE_RE.match(value.strip()))


def parse_money(raw: str | None) -> Decimal | None:
    """«12 500,50» -> Decimal('12500.50'). None, если значение некорректно."""
    if raw is None:
        return None
    cleaned = (
        str(raw)
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
        .replace("₽", "")
        .strip()
    )
    if not cleaned:
        return Decimal("0.00")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value < 0 or value > Decimal("99999999"):
        return None
    return value.quantize(Decimal("0.01"))


def parse_positive_int(raw: str | None, minimum: int = 1) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= minimum else None


def validate_password(password: str, password_repeat: str | None = None) -> str | None:
    if len(password or "") < 8:
        return "Пароль должен содержать минимум 8 символов."
    if password_repeat is not None and password != password_repeat:
        return "Пароли не совпадают."
    return None


def generate_request_number(db: Session) -> str:
    """Номер вида RM-2026-0042, уникальный в пределах года."""
    year = datetime.now().year
    prefix = f"RM-{year}-"
    count = db.scalar(
        select(func.count(RepairRequest.id)).where(
            RepairRequest.number.like(f"{prefix}%")
        )
    ) or 0
    sequence = count + 1
    while True:
        number = f"{prefix}{sequence:04d}"
        exists = db.scalar(
            select(RepairRequest.id).where(RepairRequest.number == number)
        )
        if not exists:
            return number
        sequence += 1


def recalculate_totals(request: RepairRequest) -> None:
    super_total = sum((item.unit_price * item.quantity for item in request.parts), Decimal("0"))
    request.total_cost = (request.labor_cost or Decimal("0")) + super_total


def can_transition(current: str, target: str, role: str) -> bool:
    if current == target:
        return False
    if role == ROLE_ADMIN:
        return True
    if role == "client":
        return current == STATUS_ACCEPTED and target == STATUS_CANCELLED
    return target in MASTER_TRANSITIONS.get(current, [])


def apply_status_change(
    request: RepairRequest,
    target: str,
    comment: str | None,
    user_id: int,
    role: str,
) -> None:
    """Меняет статус и пишет запись в журнал. Вызывать после проверки перехода."""
    request.status = target
    request.updated_at = now()
    if target in (STATUS_ISSUED, STATUS_CANCELLED):
        request.completed_at = now()
    request.status_logs.append(
        RequestStatusLog(
            status=target, comment=comment, user_id=user_id, created_at=now()
        )
    )


def _sniff_extension(content: bytes, filename: str) -> str | None:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in ("jpg", "jpeg"):
        suffix = "jpg"
    if suffix not in ALLOWED_IMAGE_EXTENSIONS and f".{suffix}" not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    signatures = IMAGE_SIGNATURES.get(suffix)
    if signatures and not any(content.startswith(sig) for sig in signatures):
        return None
    return suffix


def save_upload(upload: UploadFile | None) -> str | None:
    """Сохраняет фото заявки в static/uploads, возвращает относительный путь."""
    if upload is None or not upload.filename:
        return None
    content = upload.file.read(MAX_UPLOAD_SIZE + 1)
    if not content:
        return None
    if len(content) > MAX_UPLOAD_SIZE:
        raise ValueError("Файл больше 5 МБ. Загрузите фотографию меньшего размера.")
    extension = _sniff_extension(content, upload.filename)
    if extension is None:
        raise ValueError("Допустимы только изображения JPG, PNG, GIF или WEBP.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return f"uploads/{filename}"


def set_flash(response, text: str, category: str = "success") -> None:
    payload = base64.urlsafe_b64encode(
        json.dumps({"text": text, "category": category}, ensure_ascii=False).encode(
            "utf-8"
        )
    ).decode("ascii")
    response.set_cookie(
        "workshop_flash",
        payload.rstrip("="),
        max_age=60,
        httponly=True,
        samesite="lax",
    )


def flash_redirect(url: str, text: str, category: str = "success") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    set_flash(response, text, category)
    return response