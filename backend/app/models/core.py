"""Core business tables. Every one of them carries store_id."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimeStamp, utcnow


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("store_id", "phone", name="uq_customer_store_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(16), nullable=False)
    dob: Mapped[date | None] = mapped_column(Date)
    anniversary: Mapped[date | None] = mapped_column(Date)
    family_head_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    # Consent, not an afterthought: the reminder engine skips anyone who is off.
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)

    records: Mapped[list["CustomerRecord"]] = relationship(back_populates="customer")


class CustomerRecord(Base):
    """Append-only. A prescription, a set of measurements, a warranty. Never UPDATE."""

    __tablename__ = "customer_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(48), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="records")


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (UniqueConstraint("store_id", "name", name="uq_category_store_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("store_id", "sku", name="uq_product_store_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"), index=True)
    hsn_code: Mapped[str | None] = mapped_column(String(12))
    cost_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    sell_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    image_url: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    stock: Mapped["StockLevel"] = relationship(
        back_populates="product", uselist=False, cascade="all, delete-orphan"
    )
    category: Mapped["ProductCategory"] = relationship()


class StockLevel(Base):
    __tablename__ = "stock_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, unique=True)
    qty_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("0")
    )
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("0")
    )
    last_received_at: Mapped[datetime | None] = mapped_column(TimeStamp)
    last_sold_at: Mapped[datetime | None] = mapped_column(TimeStamp)

    product: Mapped[Product] = relationship(back_populates="stock")


class Batch(Base):
    """Populated only when the expiry feature flag is on for the store."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    batch_no: Mapped[str] = mapped_column(String(48), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("store_id", "invoice_no", name="uq_txn_store_invoice"),
        Index("ix_txn_store_created", "store_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_no: Mapped[str] = mapped_column(String(32), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    gst_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    payment_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="cash")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)

    items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )
    customer: Mapped["Customer"] = relationship()


class TransactionItem(Base):
    __tablename__ = "transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_discount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Which batches this line consumed, when the vertical tracks expiry.
    batch_allocation: Mapped[list | None] = mapped_column(JSON)

    transaction: Mapped[Transaction] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Job(Base):
    """Populated only when the jobs feature flag is on for the store."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    promised_date: Mapped[date | None] = mapped_column(Date)
    ready_at: Mapped[datetime | None] = mapped_column(TimeStamp)
    delivered_at: Mapped[datetime | None] = mapped_column(TimeStamp)


class DailySalesSummary(Base):
    __tablename__ = "daily_sales_summary"
    __table_args__ = (UniqueConstraint("store_id", "date", name="uq_daily_summary_store_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    invoices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    net: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    unique_customers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_customers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
