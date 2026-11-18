# Модель данных

СУБД — SQLite. Схема создаётся SQLAlchemy из моделей `app/models.py`; внешние ключи включены через `PRAGMA foreign_keys=ON`.

## ER-диаграмма

```mermaid
erDiagram
    USERS ||--o{ REPAIR_REQUESTS : "клиент"
    USERS ||--o{ REPAIR_REQUESTS : "мастер"
    USERS ||--o{ REQUEST_COMMENTS : "автор"
    USERS ||--o{ REQUEST_STATUS_LOGS : "изменил"
    SERVICES ||--o{ REPAIR_REQUESTS : "услуга"
    REPAIR_REQUESTS ||--o{ REQUEST_STATUS_LOGS : "история"
    REPAIR_REQUESTS ||--o{ REQUEST_COMMENTS : "комментарии"
    REPAIR_REQUESTS ||--o{ REQUEST_PARTS : "использовано"
    PARTS ||--o{ REQUEST_PARTS : "списано"

    USERS {
        int id PK
        string email UK
        string password_hash
        string full_name
        string phone
        string role "client | master | admin"
        bool is_active
        datetime created_at
    }
    SERVICES {
        int id PK
        string name
        string category
        text description
        numeric price_from
        int duration_days
        bool is_active
        datetime created_at
    }
    PARTS {
        int id PK
        string sku UK
        string name
        string unit
        int quantity
        int min_quantity
        numeric price
        bool is_active
        datetime created_at
        datetime updated_at
    }
    REPAIR_REQUESTS {
        int id PK
        string number UK
        int client_id FK
        int master_id FK "NULL = не назначен"
        int service_id FK "NULL = диагностика"
        string device_type
        string brand_model
        string serial_number
        text description
        string photo_path
        string status
        numeric labor_cost
        numeric total_cost
        datetime created_at
        datetime updated_at
        datetime completed_at
    }
    REQUEST_STATUS_LOGS {
        int id PK
        int request_id FK
        string status
        text comment
        int user_id FK
        datetime created_at
    }
    REQUEST_COMMENTS {
        int id PK
        int request_id FK
        int author_id FK
        text body
        bool is_internal
        datetime created_at
    }
    REQUEST_PARTS {
        int id PK
        int request_id FK
        int part_id FK
        int quantity
        numeric unit_price
        datetime created_at
    }
```

## Таблицы

### `users`
Пользователи всех ролей. `email` уникален, `role` принимает `client`, `master`, `admin`. `is_active = 0` блокирует вход, но сохраняет историю заявок. Пароль хранится как `pbkdf2_sha256$итерации$соль$хеш`.

### `services`
Каталог услуг. `price_from` — ориентировочная цена «от», `duration_days` — плановый срок. `is_active = 0` скрывает услугу из каталога и выбора в новой заявке, но оставляет её в старых заявках.

### `parts`
Склад запчастей. `sku` уникален. `quantity` — текущий остаток, `min_quantity` — порог предупреждения (`quantity <= min_quantity`). Остаток меняется мастером при списании и администратором операциями прихода/списания.

### `repair_requests`
Заявка на ремонт. `number` формата `RM-ГГГГ-0001` уникален. `master_id = NULL` — заявка ещё не распределена. `status` — одно из значений: `accepted`, `diagnostics`, `in_repair`, `ready`, `issued`, `cancelled`. `labor_cost` — работы, `total_cost` = работы + сумма запчастей (пересчитывается при изменениях).

### `request_status_logs`
Журнал переходов: кто и когда изменил статус, с каким комментарием. Используется для таймлайна в карточках и аудита.

### `request_comments`
Комментарии мастера и администратора. `is_internal = 1` — внутренняя заметка, клиенту не показывается.

### `request_parts`
Фактически использованные запчасти. `unit_price` фиксирует цену на момент списания, поэтому изменение прайса склада не искажает стоимость старых заявок. Пара `(request_id, part_id)` уникальна — повторное добавление увеличивает количество существующей строки.

## Ограничения целостности

| Ограничение | Реализация |
| --- | --- |
| Уникальность e-mail | `users.email UNIQUE` |
| Уникальность артикула | `parts.sku UNIQUE` |
| Уникальность номера заявки | `repair_requests.number UNIQUE` |
| Одна строка запчасти на заявку | `UNIQUE(request_id, part_id)` |
| Каскадное удаление истории | `ON DELETE CASCADE` для журналов, комментариев и запчастей заявки |
| Запрет удаления клиента с заявками | `ON DELETE RESTRICT` для `client_id` |
| Сохранение заявки при удалении мастера/услуги | `ON DELETE SET NULL` |
| Запрет удаления используемой запчасти | `ON DELETE RESTRICT` для `part_id` |
| Допустимые статусы и роли | проверка на уровне приложения (`constants.py`, валидаторы роутеров) |
| Неотрицательные цены и остатки | валидация `parse_money`, `parse_positive_int`, проверки склада |

## Индексы

- `ix_repair_requests_status` — фильтры списков заявок;
- `ix_repair_requests_client`, `ix_repair_requests_master` — кабинеты клиента и мастера;
- `ix_repair_requests_created_at` — сортировка и статистика по датам;
- уникальные индексы по `email`, `sku`, `number`.