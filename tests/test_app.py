"""Приёмочные тесты основных сценариев."""
import base64

from app.config import UPLOAD_DIR
from app.db import SessionLocal
from app.models import RepairRequest, User
from tests.conftest import login


def test_public_pages(client):
    assert client.get("/health").json() == {"status": "ok"}
    home = client.get("/")
    assert home.status_code == 200
    assert "Ремонтная" in home.text
    catalog = client.get("/catalog")
    assert catalog.status_code == 200
    assert "Услуги и цены" in catalog.text


def test_login_and_role_access(anon):
    assert anon.get("/admin", follow_redirects=False).status_code == 303

    response = login(anon, "client@workshop.ru", "client12345")
    assert response.status_code == 303
    assert response.headers["location"] == "/client"
    assert anon.get("/client").status_code == 200
    assert anon.get("/admin", follow_redirects=False).status_code == 303

    master = login(anon, "master@workshop.ru", "master12345")
    assert master.headers["location"] == "/master"
    assert anon.get("/master").status_code == 200
    assert anon.get("/client", follow_redirects=False).status_code == 303


def test_wrong_password(anon):
    response = login(anon, "client@workshop.ru", "wrong-password")
    assert response.status_code == 400
    assert "Неверный e-mail или пароль" in response.text


def test_csrf_required(anon):
    anon.get("/login")
    response = anon.post(
        "/login",
        data={"email": "client@workshop.ru", "password": "client12345", "csrf_token": "fake"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_full_request_flow(client):
    login(client, "client@workshop.ru", "client12345")
    token = client.cookies.get("workshop_csrf")
    before_uploads = set(UPLOAD_DIR.glob("*"))
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    created = client.post(
        "/client/requests/new",
        data={
            "device_type": "Ноутбук",
            "brand_model": "TestBook 15",
            "serial_number": "TEST-001",
            "description": "Не включается после залития, индикатор не горит.",
            "csrf_token": token,
        },
        files={"photo": ("device.png", png, "image/png")},
        follow_redirects=False,
    )
    assert created.status_code == 303
    location = created.headers["location"]
    assert location.startswith("/client/requests/")

    page = client.get(location)
    assert page.status_code == 200
    assert "TEST-001" in page.text
    assert "/static/uploads/" in page.text

    request_id = int(location.rstrip("/").split("/")[-1])
    with SessionLocal() as db:
        request = db.get(RepairRequest, request_id)
        assert request is not None
        assert request.status == "accepted"
        master = db.query(User).filter(User.email == "master@workshop.ru").one()
        master_id = master.id

    # Клиент не должен открывать чужую заявку.
    other = login(client, "client2@workshop.ru", "client12345")
    assert other.status_code == 303
    assert client.get(location).status_code == 404

    # Администратор назначает мастера и переводит в диагностику.
    login(client, "admin@workshop.ru", "admin12345")
    token = client.cookies.get("workshop_csrf")
    assigned = client.post(
        f"/admin/requests/{request_id}/assign",
        data={"master_id": str(master_id), "csrf_token": token},
        follow_redirects=False,
    )
    assert assigned.status_code == 303
    changed = client.post(
        f"/admin/requests/{request_id}/status",
        data={"status": "diagnostics", "comment": "Диагностика", "csrf_token": token},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert "В диагностике" in client.get(f"/admin/requests/{request_id}").text

    # Мастер видит заявку и ведёт её дальше.
    login(client, "master@workshop.ru", "master12345")
    token = client.cookies.get("workshop_csrf")
    master_page = client.get(f"/master/requests/{request_id}")
    assert master_page.status_code == 200
    assert "TEST-001" in master_page.text

    moved = client.post(
        f"/master/requests/{request_id}/status",
        data={"status": "in_repair", "comment": "Ремонт начат", "csrf_token": token},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    with SessionLocal() as db:
        request = db.get(RepairRequest, request_id)
        assert request.status == "in_repair"
        assert len(request.status_logs) >= 3

    for uploaded in set(UPLOAD_DIR.glob("*")) - before_uploads:
        uploaded.unlink()