"""Роли, статусы заявок и правила переходов между ними."""
from datetime import datetime

ROLE_CLIENT = "client"
ROLE_MASTER = "master"
ROLE_ADMIN = "admin"

ROLE_LABELS = {
    ROLE_CLIENT: "Клиент",
    ROLE_MASTER: "Мастер",
    ROLE_ADMIN: "Администратор",
}

STATUS_ACCEPTED = "accepted"
STATUS_DIAGNOSTICS = "diagnostics"
STATUS_IN_REPAIR = "in_repair"
STATUS_READY = "ready"
STATUS_ISSUED = "issued"
STATUS_CANCELLED = "cancelled"

STATUS_META = {
    STATUS_ACCEPTED: {"label": "Принята", "css": "accepted"},
    STATUS_DIAGNOSTICS: {"label": "В диагностике", "css": "diagnostics"},
    STATUS_IN_REPAIR: {"label": "В ремонте", "css": "in-repair"},
    STATUS_READY: {"label": "Готова к выдаче", "css": "ready"},
    STATUS_ISSUED: {"label": "Выдана", "css": "issued"},
    STATUS_CANCELLED: {"label": "Отменена", "css": "cancelled"},
}

# Статусы, при которых заявка считается активной (ещё в работе).
ACTIVE_STATUSES = [
    STATUS_ACCEPTED,
    STATUS_DIAGNOSTICS,
    STATUS_IN_REPAIR,
    STATUS_READY,
]
# Все статусы в порядке жизненного цикла — для фильтров и выпадающих списков.
ALL_STATUSES = [
    STATUS_ACCEPTED,
    STATUS_DIAGNOSTICS,
    STATUS_IN_REPAIR,
    STATUS_READY,
    STATUS_ISSUED,
    STATUS_CANCELLED,
]

# Разрешённые переходы для мастера. Администратор может перевести заявку
# в любой статус, клиент — только отменить новую заявку.
MASTER_TRANSITIONS = {
    STATUS_ACCEPTED: [STATUS_DIAGNOSTICS, STATUS_CANCELLED],
    STATUS_DIAGNOSTICS: [STATUS_IN_REPAIR, STATUS_READY, STATUS_CANCELLED],
    STATUS_IN_REPAIR: [STATUS_READY, STATUS_CANCELLED],
    STATUS_READY: [STATUS_ISSUED],
    STATUS_ISSUED: [],
    STATUS_CANCELLED: [],
}

DEVICE_TYPES = [
    "Смартфон",
    "Ноутбук",
    "Планшет",
    "Телевизор",
    "Монитор",
    "Бытовая техника",
    "Аудиотехника",
    "Другое",
]

PART_UNITS = ["шт.", "компл.", "м", "г", "л"]

STATUS_LABELS = {key: value["label"] for key, value in STATUS_META.items()}


def now() -> datetime:
    """Текущее локальное время без таймзоны (совместимо с SQLite)."""
    return datetime.now().replace(microsecond=0)