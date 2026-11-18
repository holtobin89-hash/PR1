"""ORM-модели предметной области."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import (
    ROLE_CLIENT,
    STATUS_ACCEPTED,
    now,
)
from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(20), default=ROLE_CLIENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    client_requests: Mapped[list["RepairRequest"]] = relationship(
        back_populates="client",
        foreign_keys="RepairRequest.client_id",
    )
    master_requests: Mapped[list["RepairRequest"]] = relationship(
        back_populates="master",
        foreign_keys="RepairRequest.master_id",
    )
    comments: Mapped[list["RequestComment"]] = relationship(back_populates="author")

    @property
    def is_client(self) -> bool:
        return self.role == "client"

    @property
    def is_master(self) -> bool:
        return self.role == "master"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="Прочее", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_from: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    duration_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    requests: Mapped[list["RepairRequest"]] = relationship(back_populates="service")

    @property
    def price_display(self) -> str:
        return f"{self.price_from:,.0f}".replace(",", " ")


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="шт.", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    usages: Mapped[list["RequestPart"]] = relationship(back_populates="part")

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.min_quantity


class RepairRequest(Base):
    __tablename__ = "repair_requests"
    __table_args__ = (
        Index("ix_requests_status", "status"),
        Index("ix_requests_client", "client_id"),
        Index("ix_requests_master", "master_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    master_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL")
    )
    device_type: Mapped[str] = mapped_column(String(60), nullable=False)
    brand_model: Mapped[str | None] = mapped_column(String(150))
    serial_number: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    photo_path: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_ACCEPTED, nullable=False
    )
    labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    client: Mapped[User] = relationship(
        back_populates="client_requests", foreign_keys=[client_id]
    )
    master: Mapped[User | None] = relationship(
        back_populates="master_requests", foreign_keys=[master_id]
    )
    service: Mapped[Service | None] = relationship(back_populates="requests")
    status_logs: Mapped[list["RequestStatusLog"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RequestStatusLog.created_at",
    )
    comments: Mapped[list["RequestComment"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RequestComment.created_at",
    )
    parts: Mapped[list["RequestPart"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
    )

    @property
    def parts_total(self) -> Decimal:
        return sum(
            (item.unit_price * item.quantity for item in self.parts), Decimal("0.00")
        )

    @property
    def public_comments(self) -> list["RequestComment"]:
        return [comment for comment in self.comments if not comment.is_internal]


class RequestStatusLog(Base):
    __tablename__ = "request_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("repair_requests.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    request: Mapped[RepairRequest] = relationship(back_populates="status_logs")
    user: Mapped[User | None] = relationship()


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("repair_requests.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    request: Mapped[RepairRequest] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship(back_populates="comments")


class RequestPart(Base):
    __tablename__ = "request_parts"
    __table_args__ = (
        UniqueConstraint("request_id", "part_id", name="uq_request_part"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("repair_requests.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    request: Mapped[RepairRequest] = relationship(back_populates="parts")
    part: Mapped[Part] = relationship(back_populates="usages")

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity