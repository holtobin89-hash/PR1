"""Рендеринг шаблонов: фильтры, всплывающие сообщения, общий контекст."""
import base64
import json
from decimal import Decimal, InvalidOperation

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import CSRF_COOKIE, TEMPLATES_DIR
from .constants import (
    ALL_STATUSES,
    DEVICE_TYPES,
    ROLE_LABELS,
    STATUS_LABELS,
    STATUS_META,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def money(value) -> str:
    """12345.5 -> «12 346 ₽» (без копеек, как принято в прайсах)."""
    if value is None:
        return "—"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    formatted = f"{number:,.0f}".replace(",", " ")
    return f"{formatted} ₽"


def money_exact(value) -> str:
    if value is None:
        return "—"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    formatted = f"{number:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} ₽"


def datetime_ru(value, with_time: bool = True) -> str:
    if not value:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M") if with_time else value.strftime("%d.%m.%Y")


def date_ru(value) -> str:
    return datetime_ru(value, with_time=False)


def plural_ru(number: int, one: str, few: str, many: str) -> str:
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def short_number(value: str) -> str:
    return value.replace("RM-", "№")


templates.env.filters["money"] = money
templates.env.filters["money_exact"] = money_exact
templates.env.filters["datetime_ru"] = datetime_ru
templates.env.filters["date_ru"] = date_ru

templates.env.globals.update(
    STATUS_META=STATUS_META,
    STATUS_LABELS=STATUS_LABELS,
    ALL_STATUSES=ALL_STATUSES,
    DEVICE_TYPES=DEVICE_TYPES,
    ROLE_LABELS=ROLE_LABELS,
    plural_ru=plural_ru,
    short_number=short_number,
)


def _read_flash(request: Request) -> dict | None:
    raw = request.cookies.get("workshop_flash")
    if not raw:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("text"):
        return None
    return {"text": data["text"], "category": data.get("category", "success")}


def render(
    request: Request,
    template_name: str,
    context: dict | None = None,
    status_code: int = 200,
):
    flash = _read_flash(request)
    if flash:
        request.state.clear_flash = True
    payload = {
        "request": request,
        "current_user": getattr(request.state, "user", None),
        "flash": flash,
        "csrf_token": getattr(request.state, "new_csrf_token", None)
        or request.cookies.get(CSRF_COOKIE, ""),
        "active": "",
    }
    payload.update(context or {})
    return templates.TemplateResponse(
        request, template_name, payload, status_code=status_code
    )