"""Регистрация, вход и выход."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import SESSION_COOKIE, SESSION_MAX_AGE
from ..constants import ROLE_CLIENT
from ..db import get_db
from ..deps import RedirectTo, csrf_protect, get_current_user, landing_for
from ..models import User
from ..security import create_session_token, hash_password, verify_password
from ..templating import render
from ..utils import (
    flash_redirect,
    is_valid_email,
    is_valid_phone,
    normalize_email,
    set_flash,
    validate_password,
)

router = APIRouter(dependencies=[Depends(csrf_protect)])


def _safe_next(value: str | None, fallback: str) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


@router.get("/login")
def login_page(
    request: Request,
    next: str | None = None,
    user: User | None = Depends(get_current_user),
):
    if user is not None:
        raise RedirectTo(landing_for(user))
    return render(request, "auth/login.html", {"next": next or "", "active": ""})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        return render(
            request,
            "auth/login.html",
            {
                "error": "Неверный e-mail или пароль.",
                "email": email,
                "next": next,
            },
            status_code=400,
        )
    if not user.is_active:
        return render(
            request,
            "auth/login.html",
            {
                "error": "Учётная запись заблокирована администратором.",
                "email": email,
                "next": next,
            },
            status_code=403,
        )

    response = RedirectResponse(_safe_next(next, landing_for(user)), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, user.role),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    set_flash(response, f"Добро пожаловать, {user.full_name}!")
    return response


@router.get("/register")
def register_page(
    request: Request, user: User | None = Depends(get_current_user)
):
    if user is not None:
        raise RedirectTo(landing_for(user))
    return render(request, "auth/register.html", {"form": {}})


@router.post("/register")
def register(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    password: str = Form(""),
    password_repeat: str = Form(""),
    db: Session = Depends(get_db),
):
    form = {
        "full_name": full_name.strip(),
        "email": normalize_email(email),
        "phone": phone.strip(),
    }
    errors: list[str] = []
    if len(form["full_name"]) < 2:
        errors.append("Укажите имя и фамилию.")
    if not is_valid_email(form["email"]):
        errors.append("Введите корректный e-mail.")
    if not is_valid_phone(form["phone"]):
        errors.append("Телефон должен содержать 7–30 цифр и символов + ( ) -.")
    password_error = validate_password(password, password_repeat)
    if password_error:
        errors.append(password_error)

    if not errors and db.scalar(select(User).where(User.email == form["email"])):
        errors.append("Пользователь с таким e-mail уже зарегистрирован.")

    if errors:
        return render(
            request,
            "auth/register.html",
            {"form": form, "errors": errors},
            status_code=400,
        )

    user = User(
        email=form["email"],
        password_hash=hash_password(password),
        full_name=form["full_name"],
        phone=form["phone"] or None,
        role=ROLE_CLIENT,
    )
    db.add(user)
    db.commit()

    response = RedirectResponse("/client", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, user.role),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    set_flash(response, "Регистрация завершена. Создайте первую заявку на ремонт.")
    return response


@router.post("/logout")
def logout():
    response = flash_redirect("/", "Вы вышли из системы.", "info")
    response.delete_cookie(SESSION_COOKIE)
    return response