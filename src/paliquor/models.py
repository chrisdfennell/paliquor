"""SQLAlchemy models.

The catalog (products, UPCs) is durable; inventory is a *cache* with a fetched
timestamp so we can honor a TTL and refetch on demand rather than hammering.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String, unique=True, index=True)  # e.g. 000004078
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    category_code: Mapped[str | None] = mapped_column(String, index=True)
    category_label: Mapped[str | None] = mapped_column(String)
    varietal: Mapped[str | None] = mapped_column(String)
    size: Mapped[str | None] = mapped_column(String)
    price: Mapped[float | None] = mapped_column(Float)
    image_url: Mapped[str | None] = mapped_column(String)
    baseline_stock_status: Mapped[str | None] = mapped_column(String)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    upcs: Mapped[list["Upc"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    inventory: Mapped[list["InventoryCache"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class Upc(Base):
    __tablename__ = "upcs"
    __table_args__ = (UniqueConstraint("product_id", "code", name="uq_product_upc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    code: Mapped[str] = mapped_column(String, index=True)

    product: Mapped[Product] = relationship(back_populates="upcs")


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String)
    county: Mapped[str | None] = mapped_column(String, index=True)
    city: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    zip_code: Mapped[str | None] = mapped_column(String)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class InventoryCache(Base):
    """One row per (product, store) — the last known stock, with a timestamp."""
    __tablename__ = "inventory_cache"
    __table_args__ = (
        UniqueConstraint("product_id", "store_id", name="uq_inventory_prod_store"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    product: Mapped[Product] = relationship(back_populates="inventory")
    store: Mapped[Store] = relationship()
