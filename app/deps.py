"""Зависимости FastAPI: текущий пользователь, роли, CSRF."""
import urllib.parse

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import CSRF_COOKIE, SESSION_COOKIE
from .constants import ROLE_ADMIN, ROLE_CLIENT, ROLE_MASTER
from .db import get_db
from .models import User
from .security import check_csrf, read_session_token


class RedirectTo(Exception):
    """Прерывает обработку запроса и перенаправляет пользователя."""

    def __init__(self, url: str, status_code: int = 303):
        self.url = url
        self.status_code = status_code
        super().__init__(url)


def landing_for(user: User | None) -> str:
    if user is None:
        return "/"
    return {
        ROLE_ADMIN: "/admin",
        ROLE_MASTER: "/master",
        ROLE_CLIENT: "/client",
    }.get(user.role, "/")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Читает подписанную cookie и подгружает пользователя из БД."""
    token = request.cookies.get(SESSION_COOKIE)
    data = read_session_token(token) if token else None
    user = db.get(User, data["uid"]) if data else None
    if user is not None and not user.is_active:
        user = None
    if user is not None and data and data.get("role") != user.role:
        user = None
    request.state.user = user
    return user


def require_user(
    request: Request, user: User | None = Depends(get_current_user)
) -> User:
    if user is None:
        target = request.url.path
        query = f"?next={urllib.parse.quote(target)}" if request.method == "GET" else ""
        raise RedirectTo(f"/login{query}")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise RedirectTo(landing_for(user))
        return user

    return dependency


async def csrf_protect(request: Request) -> None:
    """Double-submit cookie: значение из формы должно совпасть с cookie."""
    if request.method != "POST":
        return
    form = await request.form()
    token = form.get("csrf_token")
    if not check_csrf(request.cookies.get(CSRF_COOKIE), str(token) if token else None):
        raise HTTPException(
            status_code=400,
            detail="Сессия формы устарела. Обновите страницу и попробуйте снова.",
        )