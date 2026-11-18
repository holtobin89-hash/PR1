"""Настройки приложения и пути к ресурсам."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'workshop.db').as_posix()}",
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me-in-production")
SESSION_COOKIE = "workshop_session"
CSRF_COOKIE = "workshop_csrf"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 дней

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 МБ
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}