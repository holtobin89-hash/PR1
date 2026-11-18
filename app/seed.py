"""Демонстрационные данные: сотрудники, клиенты, услуги, склад, заявки."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .constants import (
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_MASTER,
    STATUS_ACCEPTED,
    STATUS_DIAGNOSTICS,
    STATUS_IN_REPAIR,
    STATUS_ISSUED,
    STATUS_READY,
    now,
)
from .db import SessionLocal
from .models import (
    Part,
    RepairRequest,
    RequestComment,
    RequestPart,
    RequestStatusLog,
    Service,
    User,
)
from .security import hash_password
from .utils import generate_request_number, recalculate_totals

SERVICES = [
    ("Диагностика", "Диагностика неисправности", "Поиск причины неисправности, составление сметы.", 0, 1),
    ("Ремонт смартфонов", "Замена экрана смартфона", "Замена дисплейного модуля, проверка тачскрина.", 3500, 1),
    ("Ремонт смартфонов", "Замена аккумулятора", "Установка новой АКБ с проверкой ёмкости.", 1900, 1),
    ("Ремонт смартфонов", "Чистка разъёма зарядки", "Чистка и восстановление контактов разъёма.", 900, 1),
    ("Ремонт ноутбуков", "Чистка системы охлаждения", "Разборка, чистка радиатора и замена термопасты.", 2500, 2),
    ("Ремонт ноутбуков", "Замена клавиатуры", "Замена клавиатурного модуля ноутбука.", 3200, 2),
    ("Ремонт ноутбуков", "Восстановление после залития", "Промывка платы, ремонт цепей питания.", 4800, 4),
    ("Ремонт бытовой техники", "Ремонт стиральной машины", "Диагностика и замена изношенных узлов.", 3900, 3),
    ("Ремонт бытовой техники", "Ремонт микроволновой печи", "Замена магнетрона или трансформатора.", 2900, 2),
    ("Ремонт телевизоров", "Замена подсветки телевизора", "Замена светодиодных линеек подсветки.", 5200, 4),
]

PARTS = [
    ("SCR-IP11", "Дисплейный модуль iPhone 11", "шт.", 4, 2, 7900),
    ("BAT-IP11", "Аккумулятор iPhone 11", "шт.", 8, 3, 2400),
    ("BAT-SAM-A52", "Аккумулятор Samsung A52", "шт.", 2, 3, 2100),
    ("KB-LEN-T480", "Клавиатура Lenovo ThinkPad T480", "шт.", 1, 1, 3600),
    ("TP-MX4", "Термопаста Arctic MX-4", "г", 25, 10, 150),
    ("FAN-ASUS-X", "Вентилятор Asus X509", "шт.", 0, 2, 1800),
    ("LED-32", "Линейка подсветки 32\"", "компл.", 3, 1, 1200),
    ("FUSE-5A", "Предохранитель 5A", "шт.", 40, 15, 40),
]


def seed_if_empty() -> bool:
    """Наполняет пустую базу демо-данными. Возвращает True, если данные добавлены."""
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)):
            return False
        _seed(db)
        return True


def _seed(db: Session) -> None:
    admin = User(
        email="admin@workshop.ru",
        password_hash=hash_password("admin12345"),
        full_name="Иван Петров",
        phone="+7 900 100-10-10",
        role=ROLE_ADMIN,
    )
    master_1 = User(
        email="master@workshop.ru",
        password_hash=hash_password("master12345"),
        full_name="Сергей Кузнецов",
        phone="+7 900 200-20-20",
        role=ROLE_MASTER,
    )
    master_2 = User(
        email="master2@workshop.ru",
        password_hash=hash_password("master12345"),
        full_name="Анна Смирнова",
        phone="+7 900 300-30-30",
        role=ROLE_MASTER,
    )
    client = User(
        email="client@workshop.ru",
        password_hash=hash_password("client12345"),
        full_name="Ольга Иванова",
        phone="+7 900 400-40-40",
        role=ROLE_CLIENT,
    )
    client_2 = User(
        email="client2@workshop.ru",
        password_hash=hash_password("client12345"),
        full_name="Дмитрий Соколов",
        phone="+7 900 500-50-50",
        role=ROLE_CLIENT,
    )
    db.add_all([admin, master_1, master_2, client, client_2])

    services = [
        Service(
            name=name,
            category=category,
            description=description,
            price_from=Decimal(str(price)),
            duration_days=days,
        )
        for category, name, description, price, days in SERVICES
    ]
    db.add_all(services)

    parts = [
        Part(
            sku=sku,
            name=name,
            unit=unit,
            quantity=quantity,
            min_quantity=min_quantity,
            price=Decimal(str(price)),
        )
        for sku, name, unit, quantity, min_quantity, price in PARTS
    ]
    db.add_all(parts)
    db.flush()

    screen = parts[0]
    battery = parts[1]
    paste = parts[4]

    def make_request(
        client_user: User,
        master: User | None,
        service: Service,
        device: str,
        model: str,
        description: str,
        status: str,
        days_ago: int,
        labor: int,
    ) -> RepairRequest:
        created = now() - timedelta(days=days_ago, hours=2)
        item = RepairRequest(
            number=generate_request_number(db),
            client_id=client_user.id,
            master_id=master.id if master else None,
            service_id=service.id,
            device_type=device,
            brand_model=model,
            description=description,
            status=status,
            labor_cost=Decimal(str(labor)),
            total_cost=Decimal(str(labor)),
            created_at=created,
            updated_at=created,
        )
        item.status_logs.append(
            RequestStatusLog(
                status=STATUS_ACCEPTED,
                comment="Заявка создана клиентом.",
                user_id=client_user.id,
                created_at=created,
            )
        )
        if status != STATUS_ACCEPTED:
            item.status_logs.append(
                RequestStatusLog(
                    status=STATUS_DIAGNOSTICS,
                    comment="Принято в диагностику.",
                    user_id=master.id if master else admin.id,
                    created_at=created + timedelta(hours=3),
                )
            )
        if status in (STATUS_IN_REPAIR, STATUS_READY, STATUS_ISSUED):
            item.status_logs.append(
                RequestStatusLog(
                    status=STATUS_IN_REPAIR,
                    comment="Неисправность подтверждена, начинаем ремонт.",
                    user_id=master.id if master else admin.id,
                    created_at=created + timedelta(days=1),
                )
            )
        if status in (STATUS_READY, STATUS_ISSUED):
            item.status_logs.append(
                RequestStatusLog(
                    status=STATUS_READY,
                    comment="Ремонт завершён, устройство можно забирать.",
                    user_id=master.id if master else admin.id,
                    created_at=created + timedelta(days=2),
                )
            )
        if status == STATUS_ISSUED:
            item.status_logs.append(
                RequestStatusLog(
                    status=STATUS_ISSUED,
                    comment="Выдано клиенту.",
                    user_id=admin.id,
                    created_at=created + timedelta(days=3),
                )
            )
            item.completed_at = created + timedelta(days=3)
            item.updated_at = item.completed_at
        db.add(item)
        db.flush()
        return item

    screen_request = make_request(
        client,
        master_1,
        services[1],
        "Смартфон",
        "Apple iPhone 11",
        "Разбит экран после падения, сенсор работает частично.",
        STATUS_IN_REPAIR,
        4,
        3500,
    )
    screen_request.parts.append(
        RequestPart(
            part_id=screen.id,
            quantity=1,
            unit_price=screen.price,
            created_at=now() - timedelta(days=3),
        )
    )
    screen.quantity -= 1
    screen_request.comments.append(
        RequestComment(
            author_id=master_1.id,
            body="Дисплей в наличии, меняем сегодня. Заберите устройство после 18:00.",
            created_at=now() - timedelta(days=3, hours=1),
        )
    )

    issued_request = make_request(
        client_2,
        master_2,
        services[5],
        "Ноутбук",
        "Lenovo ThinkPad T480",
        "Не работают часть клавиш после попадания жидкости.",
        STATUS_ISSUED,
        12,
        3200,
    )
    issued_request.parts.append(
        RequestPart(
            part_id=battery.id,
            quantity=1,
            unit_price=battery.price,
            created_at=now() - timedelta(days=11),
        )
    )
    battery.quantity -= 1
    recalculate_totals(issued_request)
    issued_request.comments.append(
        RequestComment(
            author_id=admin.id,
            body="Клиент оплатил ремонт, выдан акт приёма-передачи.",
            created_at=now() - timedelta(days=9),
        )
    )

    make_request(
        client,
        None,
        services[0],
        "Телевизор",
        "LG 43UM7450",
        "Телевизор включается, но изображение пропадает через 10 минут — нужна диагностика.",
        STATUS_ACCEPTED,
        0,
        0,
    )

    make_request(
        client_2,
        master_1,
        services[4],
        "Ноутбук",
        "Asus X509",
        "Сильно шумит вентилятор и греется корпус при работе.",
        STATUS_READY,
        6,
        2500,
    )

    db.commit()


if __name__ == "__main__":
    created = seed_if_empty()
    print("Демо-данные добавлены." if created else "База уже содержит данные.")