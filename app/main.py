"""Точка входа приложения «Ремонтная мастерская»."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import CSRF_COOKIE, SESSION_MAX_AGE, STATIC_DIR
from .db import init_db
from .deps import RedirectTo
from .routers import admin, auth, client, master, public
from .security import make_csrf_token
from .seed import seed_if_empty
from .templating import render


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if os.getenv("AUTO_SEED", "1") != "0":
        seed_if_empty()
    yield


app = FastAPI(title="Ремонтная мастерская", lifespan=lifespan)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Выдаёт CSRF-cookie и удаляет прочитанное flash-сообщение."""

    async def dispatch(self, request: Request, call_next):
        csrf_token = request.cookies.get(CSRF_COOKIE)
        if not csrf_token:
            csrf_token = make_csrf_token()
            request.state.new_csrf_token = csrf_token
        response = await call_next(request)
        if getattr(request.state, "clear_flash", False):
            response.delete_cookie("workshop_flash")
        if getattr(request.state, "new_csrf_token", None):
            response.set_cookie(
                CSRF_COOKIE,
                request.state.new_csrf_token,
                max_age=SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
            )
        return response


app.add_middleware(SecurityMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(client.router)
app.include_router(master.router)
app.include_router(admin.router)


@app.exception_handler(RedirectTo)
async def redirect_handler(_request: Request, exc: RedirectTo):
    return RedirectResponse(exc.url, status_code=exc.status_code)


@app.exception_handler(FastAPIHTTPException)
async def http_error_handler(request: Request, exc: FastAPIHTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Произошла ошибка."
    return render(
        request,
        "errors/error.html",
        {"code": exc.status_code, "message": message},
        status_code=exc.status_code,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, _exc):
    return render(
        request,
        "errors/404.html",
        {"message": "Страница не найдена."},
        status_code=404,
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)