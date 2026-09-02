"""Catalog services. Attributes are validated against the vertical product_schema."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit
from app.models.core import Product, ProductCategory, StockLevel
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext
from app.verticals.schemas import AttributeValidationError, validate_attributes


def _validated_attributes(context: StoreContext, attributes: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_attributes(context.product_schema, attributes)
    except AttributeValidationError as exc:
        raise ValidationError(
            f"Product attributes do not match the {context.vertical_name} schema: {exc}",
            exc.errors,
        ) from exc


# -- categories -------------------------------------------------------------
def list_categories(db: Session, context: StoreContext) -> list[ProductCategory]:
    return list(
        db.scalars(
            select(ProductCategory)
            .where(ProductCategory.store_id == context.store_id)
            .order_by(ProductCategory.name)
        ).all()
    )


def create_category(
    db: Session, context: StoreContext, payload: dict[str, Any]
) -> ProductCategory:
    existing = db.scalar(
        select(ProductCategory).where(
            ProductCategory.store_id == context.store_id,
            ProductCategory.name == payload["name"],
        )
    )
    if existing is not None:
        raise ConflictError(
            f"Category '{payload['name']}' already exists at {context.store_name}"
        )
    category = ProductCategory(store_id=context.store_id, **payload)
    db.add(category)
    db.flush()
    return category


def _auditable(product: Product) -> dict[str, Any]:
    """The fields worth keeping a history of."""
    return {
        "sku": product.sku,
        "name": product.name,
        "sell_price": str(product.sell_price),
        "cost_price": str(product.cost_price),
        "gst_rate": str(product.gst_rate),
        "is_active": product.is_active,
        "category_id": product.category_id,
    }


# -- products ---------------------------------------------------------------
def _to_out(product: Product, stock: StockLevel | None, context: StoreContext) -> dict[str, Any]:
    category_name = product.category.name if product.category else None
    return {
        "id": product.id,
        "store_id": product.store_id,
        "sku": product.sku,
        "name": product.name,
        "category_id": product.category_id,
        "category_name": category_name,
        "hsn_code": product.hsn_code,
        "cost_price": product.cost_price,
        "sell_price": product.sell_price,
        "gst_rate": product.gst_rate,
        "attributes": product.attributes or {},
        "image_url": product.image_url,
        "is_active": product.is_active,
        "qty_on_hand": stock.qty_on_hand if stock else Decimal("0"),
        "reorder_point": stock.reorder_point if stock else Decimal("0"),
        "unit_label": context.unit_label,
    }


def search_products(
    db: Session,
    context: StoreContext,
    *,
    query: str | None = None,
    category_id: int | None = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    statement = (
        select(Product, StockLevel)
        .outerjoin(StockLevel, StockLevel.product_id == Product.id)
        .where(Product.store_id == context.store_id)
    )
    if active_only:
        statement = statement.where(Product.is_active.is_(True))
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    if category_id:
        statement = statement.where(Product.category_id == category_id)
    statement = statement.order_by(Product.name).limit(limit).offset(offset)
    return [_to_out(product, stock, context) for product, stock in db.execute(statement).all()]


def get_product(db: Session, context: StoreContext, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.store_id != context.store_id:
        raise NotFoundError(f"Product {product_id} is not in the catalog of {context.store_name}")
    return product


def get_product_out(db: Session, context: StoreContext, product_id: int) -> dict[str, Any]:
    product = get_product(db, context, product_id)
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    return _to_out(product, stock, context)


def create_product(db: Session, context: StoreContext, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    qty_on_hand = data.pop("qty_on_hand", Decimal("0"))
    reorder_point = data.pop("reorder_point", Decimal("0"))
    data["attributes"] = _validated_attributes(context, data.get("attributes") or {})

    if data.get("category_id"):
        category = db.get(ProductCategory, int(data["category_id"]))
        if category is None or category.store_id != context.store_id:
            raise NotFoundError(
                f"Category {data['category_id']} does not belong to {context.store_name}"
            )

    existing = db.scalar(
        select(Product).where(
            Product.store_id == context.store_id, Product.sku == data["sku"]
        )
    )
    if existing is not None:
        raise ConflictError(
            f"SKU {data['sku']} is already used by '{existing.name}' at {context.store_name}"
        )

    product = Product(store_id=context.store_id, **data)
    db.add(product)
    db.flush()
    db.add(
        StockLevel(
            product_id=product.id, qty_on_hand=qty_on_hand, reorder_point=reorder_point
        )
    )
    db.flush()
    audit.record(
        db,
        action="product.create",
        entity="product",
        entity_id=product.id,
        store_id=context.store_id,
        after=_auditable(product),
    )
    return get_product_out(db, context, product.id)


def update_product(
    db: Session, context: StoreContext, product_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    product = get_product(db, context, product_id)
    before = _auditable(product)
    data = {key: value for key, value in payload.items() if value is not None}
    qty_on_hand = data.pop("qty_on_hand", None)
    reorder_point = data.pop("reorder_point", None)

    if "attributes" in data:
        data["attributes"] = _validated_attributes(context, data["attributes"])
    if data.get("category_id"):
        category = db.get(ProductCategory, int(data["category_id"]))
        if category is None or category.store_id != context.store_id:
            raise NotFoundError(
                f"Category {data['category_id']} does not belong to {context.store_name}"
            )

    for key, value in data.items():
        setattr(product, key, value)

    if qty_on_hand is not None or reorder_point is not None:
        stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
        if stock is None:
            stock = StockLevel(product_id=product.id)
            db.add(stock)
        if qty_on_hand is not None:
            stock.qty_on_hand = qty_on_hand
        if reorder_point is not None:
            stock.reorder_point = reorder_point

    db.flush()

    changed_before, changed_after = audit.diff(before, _auditable(product))
    if changed_after:
        audit.record(
            db,
            action="product.update",
            entity="product",
            entity_id=product.id,
            store_id=context.store_id,
            before=changed_before,
            after=changed_after,
        )
        db.flush()

    return get_product_out(db, context, product.id)
