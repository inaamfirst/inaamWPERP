from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import Select, inspect, select
from sqlalchemy.orm import Session

from erp.packages.core.config import get_settings
from erp.packages.core.db.models import (
    Brand,
    Category,
    ExternalResourceMap,
    MarketplaceCommissionRule,
    OrderItem,
    Product,
    ProductCategoryLink,
    ProductImage,
    ProductRelationship,
    ProductTag,
    ProductTagLink,
    ProductVariant,
    ProductVideo,
    StockMovement,
    SyncConflict,
    SyncOutbox,
    Vendor,
    VendorInventoryBalance,
    VendorInventoryMovement,
    VendorOrderItem,
    VendorProduct,
)
from erp.packages.core.schemas import (
    BrandCreate,
    BrandUpdate,
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
)
from erp.packages.core.services import ServiceError, record_audit

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
SLUG_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
PRODUCT_STATUSES = {"draft", "active", "archived"}
PRODUCT_TYPES = {"simple", "variable"}
AUTO_PRODUCT_SKU_PREFIX = "CO"
AUTO_PRODUCT_SKU_PATTERN = re.compile(r"^CO-(\d+)$")
AUTO_PRODUCT_BARCODE_PREFIX = "20"
AUTO_PRODUCT_BARCODE_PATTERN = re.compile(r"^20(\d{10})(\d)$")
RELATIONSHIP_FIELDS = {
    "upsell_ids": "upsell",
    "cross_sell_ids": "cross_sell",
    "grouped_product_ids": "grouped",
}
PRODUCT_VIDEO_MAX_COUNT = 10
YOUTUBE_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
VIMEO_VIDEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}


def table_exists(db: Session, table_name: str) -> bool:
    return inspect(db.get_bind()).has_table(table_name)


def require_company_id(company_id: str | None) -> str:
    if not company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return company_id


def slugify(value: str) -> str:
    slug = SLUG_SEPARATOR_PATTERN.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ServiceError(422, "A valid slug could not be generated.")
    return slug[:160]


def normalize_slug(name: str, slug: str | None = None) -> str:
    candidate = slugify(slug or name)
    if not SLUG_PATTERN.fullmatch(candidate):
        raise ServiceError(
            422,
            "Slug must contain lowercase letters, numbers, dots, underscores, or hyphens.",
        )
    return candidate


def validate_status(status: str) -> str:
    normalized = status.lower()
    if normalized not in PRODUCT_STATUSES:
        raise ServiceError(422, f"Unsupported product status: {status}.")
    return normalized


def validate_product_type(product_type: str) -> str:
    normalized = product_type.lower()
    if normalized not in PRODUCT_TYPES:
        raise ServiceError(422, f"Unsupported product type: {product_type}.")
    return normalized


def ensure_unique_slug(
    db: Session,
    model: type[Brand] | type[Category] | type[Product],
    *,
    company_id: str,
    slug: str,
    exclude_id: str | None = None,
) -> None:
    query = select(model.id).where(model.company_id == company_id, model.slug == slug)
    if exclude_id:
        query = query.where(model.id != exclude_id)
    if db.scalar(query):
        raise ServiceError(409, f"Slug already exists for this company: {slug}.")


def ensure_unique_sku(
    db: Session,
    *,
    company_id: str,
    sku: str | None,
    exclude_product_id: str | None = None,
    exclude_variant_id: str | None = None,
) -> None:
    if not sku:
        return
    product_query = select(Product.id).where(Product.company_id == company_id, Product.sku == sku)
    if exclude_product_id:
        product_query = product_query.where(Product.id != exclude_product_id)
    if db.scalar(product_query):
        raise ServiceError(409, f"SKU already exists for this company: {sku}.")

    variant_query = select(ProductVariant.id).where(
        ProductVariant.company_id == company_id,
        ProductVariant.sku == sku,
    )
    if exclude_variant_id:
        variant_query = variant_query.where(ProductVariant.id != exclude_variant_id)
    if db.scalar(variant_query):
        raise ServiceError(409, f"SKU already exists for this company: {sku}.")


def _scoped_string_values(db: Session, *, company_id: str, attr_name: str) -> list[str]:
    model_column = getattr(Product, attr_name)
    variant_column = getattr(ProductVariant, attr_name)
    values = [
        value
        for value in db.scalars(
            select(model_column).where(
                Product.company_id == company_id,
                model_column.is_not(None),
            )
        ).all()
        if isinstance(value, str) and value.strip()
    ]
    values.extend(
        value
        for value in db.scalars(
            select(variant_column).where(
                ProductVariant.company_id == company_id,
                variant_column.is_not(None),
            )
        ).all()
        if isinstance(value, str) and value.strip()
    )
    return values


def _next_numeric_suffix(values: list[str], pattern: re.Pattern[str]) -> int:
    next_value = 0
    for value in values:
        match = pattern.fullmatch(value)
        if match:
            next_value = max(next_value, int(match.group(1)))
    return next_value + 1


def _ean13_check_digit(body: str) -> str:
    if len(body) != 12 or not body.isdigit():
        raise ServiceError(500, "Unable to generate a barcode suggestion.")
    total = 0
    for index, char in enumerate(reversed(body)):
        weight = 3 if index % 2 == 0 else 1
        total += int(char) * weight
    return str((10 - (total % 10)) % 10)


def generate_product_sku(db: Session, company_id: str) -> str:
    values = _scoped_string_values(db, company_id=company_id, attr_name="sku")
    sequence = _next_numeric_suffix(values, AUTO_PRODUCT_SKU_PATTERN)
    return f"{AUTO_PRODUCT_SKU_PREFIX}-{sequence:06d}"


def generate_product_barcode(db: Session, company_id: str) -> str:
    values = _scoped_string_values(db, company_id=company_id, attr_name="barcode")
    sequence = _next_numeric_suffix(values, AUTO_PRODUCT_BARCODE_PATTERN)
    body = f"{AUTO_PRODUCT_BARCODE_PREFIX}{sequence:010d}"
    return f"{body}{_ean13_check_digit(body)}"


def suggest_product_codes(db: Session, company_id: str | None) -> tuple[str, str]:
    scoped_company_id = require_company_id(company_id)
    return (
        generate_product_sku(db, scoped_company_id),
        generate_product_barcode(db, scoped_company_id),
    )


def categories_query(company_id: str, include_archived: bool = False) -> Select[tuple[Category]]:
    query = select(Category).where(Category.company_id == company_id)
    if not include_archived:
        query = query.where(Category.is_active.is_(True))
    return query.order_by(Category.name)


def list_categories(
    db: Session,
    company_id: str | None,
    *,
    include_archived: bool = False,
) -> list[Category]:
    scoped_company_id = require_company_id(company_id)
    return list(db.scalars(categories_query(scoped_company_id, include_archived)).all())


def get_category(db: Session, company_id: str | None, category_id: str) -> Category:
    scoped_company_id = require_company_id(company_id)
    category = db.scalar(
        select(Category).where(Category.company_id == scoped_company_id, Category.id == category_id)
    )
    if category is None:
        raise ServiceError(404, "Category not found.")
    return category


def create_category(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: CategoryCreate,
) -> Category:
    scoped_company_id = require_company_id(company_id)
    parent_id = payload.parent_id
    if parent_id:
        get_category(db, scoped_company_id, parent_id)
    slug = normalize_slug(payload.name, payload.slug)
    ensure_unique_slug(db, Category, company_id=scoped_company_id, slug=slug)
    category = Category(
        company_id=scoped_company_id,
        parent_id=parent_id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        is_active=True,
    )
    db.add(category)
    db.flush()
    db.refresh(category)
    record_audit(
        db,
        action="catalog.category_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        metadata={"name": category.name, "slug": category.slug},
    )
    return category


def update_category(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    category_id: str,
    payload: CategoryUpdate,
) -> Category:
    scoped_company_id = require_company_id(company_id)
    category = get_category(db, scoped_company_id, category_id)
    fields = payload.model_dump(exclude_unset=True)
    if "parent_id" in fields and fields["parent_id"]:
        if fields["parent_id"] == category.id:
            raise ServiceError(422, "Category cannot be its own parent.")
        get_category(db, scoped_company_id, fields["parent_id"])
    if "slug" in fields:
        category.slug = normalize_slug(fields.get("name") or category.name, fields["slug"])
        ensure_unique_slug(
            db,
            Category,
            company_id=scoped_company_id,
            slug=category.slug,
            exclude_id=category.id,
        )
    for field in ("name", "parent_id", "description", "is_active"):
        if field in fields:
            setattr(category, field, fields[field])
    db.flush()
    db.refresh(category)
    record_audit(
        db,
        action="catalog.category_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        metadata={"updated_fields": sorted(fields)},
    )
    return category


def archive_category(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    category_id: str,
) -> None:
    scoped_company_id = require_company_id(company_id)
    category = get_category(db, scoped_company_id, category_id)
    category.is_active = False
    record_audit(
        db,
        action="catalog.category_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        metadata={"soft_delete": True},
    )


def list_brands(
    db: Session,
    company_id: str | None,
    *,
    include_archived: bool = False,
) -> list[Brand]:
    scoped_company_id = require_company_id(company_id)
    query = select(Brand).where(Brand.company_id == scoped_company_id)
    if not include_archived:
        query = query.where(Brand.is_active.is_(True))
    return list(db.scalars(query.order_by(Brand.name)).all())


def get_brand(db: Session, company_id: str | None, brand_id: str) -> Brand:
    scoped_company_id = require_company_id(company_id)
    brand = db.scalar(
        select(Brand).where(Brand.company_id == scoped_company_id, Brand.id == brand_id)
    )
    if brand is None:
        raise ServiceError(404, "Brand not found.")
    return brand


def create_brand(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: BrandCreate,
) -> Brand:
    scoped_company_id = require_company_id(company_id)
    slug = normalize_slug(payload.name, payload.slug)
    ensure_unique_slug(db, Brand, company_id=scoped_company_id, slug=slug)
    brand = Brand(
        company_id=scoped_company_id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        is_active=True,
    )
    db.add(brand)
    db.flush()
    db.refresh(brand)
    record_audit(
        db,
        action="catalog.brand_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="brand",
        entity_id=brand.id,
        metadata={"name": brand.name, "slug": brand.slug},
    )
    return brand


def update_brand(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    brand_id: str,
    payload: BrandUpdate,
) -> Brand:
    scoped_company_id = require_company_id(company_id)
    brand = get_brand(db, scoped_company_id, brand_id)
    fields = payload.model_dump(exclude_unset=True)
    if "slug" in fields:
        brand.slug = normalize_slug(fields.get("name") or brand.name, fields["slug"])
        ensure_unique_slug(
            db,
            Brand,
            company_id=scoped_company_id,
            slug=brand.slug,
            exclude_id=brand.id,
        )
    for field in ("name", "description", "is_active"):
        if field in fields:
            setattr(brand, field, fields[field])
    db.flush()
    db.refresh(brand)
    record_audit(
        db,
        action="catalog.brand_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="brand",
        entity_id=brand.id,
        metadata={"updated_fields": sorted(fields)},
    )
    return brand


def archive_brand(db: Session, *, company_id: str | None, user_id: str, brand_id: str) -> None:
    scoped_company_id = require_company_id(company_id)
    brand = get_brand(db, scoped_company_id, brand_id)
    brand.is_active = False
    record_audit(
        db,
        action="catalog.brand_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="brand",
        entity_id=brand.id,
        metadata={"soft_delete": True},
    )


def product_variants(db: Session, product_id: str) -> list[ProductVariant]:
    return list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.created_at)
        ).all()
    )


def product_images(db: Session, product_id: str) -> list[ProductImage]:
    return list(
        db.scalars(
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .where(ProductImage.sync_status != "pending_remove")
            .order_by(ProductImage.sort_order, ProductImage.created_at)
        ).all()
    )


def product_videos(db: Session, product_id: str) -> list[ProductVideo]:
    return list(
        db.scalars(
            select(ProductVideo)
            .where(ProductVideo.product_id == product_id)
            .order_by(ProductVideo.sort_order, ProductVideo.created_at)
        ).all()
    )


def product_video_source_type(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ServiceError(
            422,
            "Product video URLs must be HTTPS direct MP4, YouTube, or Vimeo links.",
        )
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.lower()
    if path.endswith(".mp4"):
        return "mp4"
    if host == "youtu.be" and re.fullmatch(r"/[A-Za-z0-9_-]{6,}", parsed.path):
        return "youtube"
    if host in YOUTUBE_VIDEO_HOSTS - {"youtu.be"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
            return "youtube"
        if len(path_parts) == 2 and path_parts[0] in {"embed", "shorts", "live"}:
            if re.fullmatch(r"[A-Za-z0-9_-]{6,}", path_parts[1]):
                return "youtube"
    if host in VIMEO_VIDEO_HOSTS:
        path_parts = [part for part in parsed.path.split("/") if part]
        if any(part.isdigit() for part in path_parts):
            return "vimeo"
    raise ServiceError(
        422,
        "Product video URLs must be direct MP4, YouTube, or Vimeo links.",
    )


def _remove_uploaded_product_video(url: str) -> None:
    if not url.startswith("/media/"):
        return
    media_root = Path(get_settings().media_upload_dir).resolve()
    relative = url.removeprefix("/media/").lstrip("/").replace("\\", "/")
    target = (media_root / relative).resolve()
    try:
        target.relative_to(media_root)
    except ValueError:
        return
    target.unlink(missing_ok=True)


def product_category_ids(db: Session, product_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ProductCategoryLink.category_id)
            .where(ProductCategoryLink.product_id == product_id)
            .order_by(ProductCategoryLink.sort_order, ProductCategoryLink.created_at)
        ).all()
    )


def product_tag_names(db: Session, product_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ProductTag.name)
            .join(ProductTagLink, ProductTagLink.tag_id == ProductTag.id)
            .where(ProductTagLink.product_id == product_id)
            .order_by(ProductTag.name)
        ).all()
    )


def product_relationship_ids(
    db: Session,
    product_id: str,
    relationship_type: str,
) -> list[str]:
    return list(
        db.scalars(
            select(ProductRelationship.target_product_id)
            .where(
                ProductRelationship.source_product_id == product_id,
                ProductRelationship.relationship_type == relationship_type,
            )
            .order_by(ProductRelationship.sort_order, ProductRelationship.created_at)
        ).all()
    )


def list_products(
    db: Session,
    company_id: str | None,
    *,
    include_archived: bool = False,
) -> list[Product]:
    scoped_company_id = require_company_id(company_id)
    query = select(Product).where(Product.company_id == scoped_company_id)
    if not include_archived:
        query = query.where(Product.status != "archived")
    return list(db.scalars(query.order_by(Product.name)).all())


def get_product(db: Session, company_id: str | None, product_id: str) -> Product:
    scoped_company_id = require_company_id(company_id)
    product = db.scalar(
        select(Product).where(Product.company_id == scoped_company_id, Product.id == product_id)
    )
    if product is None:
        raise ServiceError(404, "Product not found.")
    return product


def validate_product_references(
    db: Session,
    *,
    company_id: str,
    category_id: str | None,
    brand_id: str | None,
    vendor_id: str | None,
) -> None:
    if category_id:
        get_category(db, company_id, category_id)
    if brand_id:
        get_brand(db, company_id, brand_id)
    if vendor_id:
        vendor = db.scalar(
            select(Vendor).where(Vendor.company_id == company_id, Vendor.id == vendor_id)
        )
        if vendor is None:
            raise ServiceError(404, "Vendor not found.")


def validate_variant_skus(
    db: Session,
    *,
    company_id: str,
    product_sku: str | None,
    variants: list[Any],
) -> None:
    seen: set[str] = set()
    if product_sku:
        seen.add(product_sku)
    for variant in variants:
        if not variant.sku:
            continue
        if variant.sku in seen:
            raise ServiceError(409, f"Duplicate SKU in product payload: {variant.sku}.")
        seen.add(variant.sku)
        ensure_unique_sku(db, company_id=company_id, sku=variant.sku)


def normalized_category_ids(category_id: str | None, category_ids: list[str]) -> list[str]:
    ordered: list[str] = []
    for candidate in [category_id, *category_ids]:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def replace_product_categories(
    db: Session,
    *,
    company_id: str,
    product: Product,
    category_ids: list[str],
) -> None:
    db.query(ProductCategoryLink).filter(ProductCategoryLink.product_id == product.id).delete()
    for index, category_id in enumerate(category_ids):
        get_category(db, company_id, category_id)
        db.add(
            ProductCategoryLink(
                company_id=company_id,
                product_id=product.id,
                category_id=category_id,
                is_primary=category_id == product.category_id,
                sort_order=index,
            )
        )


def replace_product_tags(
    db: Session,
    *,
    company_id: str,
    product: Product,
    tags: list[str],
) -> None:
    db.query(ProductTagLink).filter(ProductTagLink.product_id == product.id).delete()
    seen: set[str] = set()
    for name in tags:
        tag_name = name.strip()
        if not tag_name:
            continue
        slug = slugify(tag_name)[:120]
        if slug in seen:
            continue
        seen.add(slug)
        tag = db.scalar(
            select(ProductTag).where(ProductTag.company_id == company_id, ProductTag.slug == slug)
        )
        if tag is None:
            tag = ProductTag(company_id=company_id, name=tag_name[:120], slug=slug, is_active=True)
            db.add(tag)
            db.flush()
        db.add(ProductTagLink(company_id=company_id, product_id=product.id, tag_id=tag.id))


def replace_product_relationships(
    db: Session,
    *,
    company_id: str,
    product: Product,
    relationship_type: str,
    target_ids: list[str],
) -> None:
    db.query(ProductRelationship).filter(
        ProductRelationship.source_product_id == product.id,
        ProductRelationship.relationship_type == relationship_type,
    ).delete()
    seen: set[str] = set()
    for index, target_id in enumerate(target_ids):
        if not target_id or target_id == product.id or target_id in seen:
            continue
        get_product(db, company_id, target_id)
        seen.add(target_id)
        db.add(
            ProductRelationship(
                company_id=company_id,
                source_product_id=product.id,
                target_product_id=target_id,
                relationship_type=relationship_type,
                sort_order=index,
            )
        )


def replace_product_variants(
    db: Session,
    *,
    company_id: str,
    product: Product,
    variants: list[Any],
) -> None:
    existing = {
        variant.id: variant
        for variant in db.scalars(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
        ).all()
    }
    keep_ids: set[str] = set()
    seen_skus: set[str] = {product.sku} if product.sku else set()
    for variant_payload in variants:
        if variant_payload.sku:
            if variant_payload.sku in seen_skus:
                raise ServiceError(409, f"Duplicate SKU in product payload: {variant_payload.sku}.")
            seen_skus.add(variant_payload.sku)
        variant_id = getattr(variant_payload, "id", None)
        variant = existing.get(variant_id) if variant_id else None
        if variant is None:
            ensure_unique_sku(db, company_id=company_id, sku=variant_payload.sku)
            variant = ProductVariant(company_id=company_id, product_id=product.id)
            db.add(variant)
        else:
            ensure_unique_sku(
                db,
                company_id=company_id,
                sku=variant_payload.sku,
                exclude_variant_id=variant.id,
            )
        variant.name = variant_payload.name
        variant.sku = variant_payload.sku
        variant.barcode = variant_payload.barcode
        variant.price_minor = variant_payload.price_minor
        variant.cost_minor = variant_payload.cost_minor
        variant.currency = variant_payload.currency.upper()
        variant.attributes = variant_payload.attributes
        variant.sale_price_minor = variant_payload.sale_price_minor
        variant.manage_stock = variant_payload.manage_stock
        variant.stock_quantity = variant_payload.stock_quantity
        variant.stock_status = variant_payload.stock_status
        variant.backorders = variant_payload.backorders
        variant.weight = variant_payload.weight
        variant.length = variant_payload.length
        variant.width = variant_payload.width
        variant.height = variant_payload.height
        variant.shipping_class = variant_payload.shipping_class
        variant.description = variant_payload.description
        variant.image_url = variant_payload.image_url
        variant.metadata_json = variant_payload.metadata
        variant.is_active = variant_payload.is_active
        db.flush()
        keep_ids.add(variant.id)

    for variant_id, variant in existing.items():
        if variant_id not in keep_ids:
            db.delete(variant)


def replace_product_images(
    db: Session,
    *,
    company_id: str,
    product: Product,
    images: list[Any],
) -> None:
    existing = {
        image.id: image
        for image in db.scalars(select(ProductImage).where(ProductImage.product_id == product.id))
    }
    keep_ids: set[str] = set()
    for image_payload in images:
        if image_payload.variant_id:
            variant = db.scalar(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.product_id == product.id,
                    ProductVariant.id == image_payload.variant_id,
                )
            )
            if variant is None:
                raise ServiceError(422, "Image variant does not belong to this product.")
        image_id = getattr(image_payload, "id", None)
        image = existing.get(image_id) if image_id else None
        if image is None:
            image = ProductImage(
                company_id=company_id,
                product_id=product.id,
                url=image_payload.url,
            )
            db.add(image)
        image.variant_id = image_payload.variant_id
        prior_url = image.url
        prior_name = image.name
        prior_alt_text = image.alt_text
        prior_sort_order = image.sort_order
        had_external_id = bool(image.external_id)
        image.external_id = image_payload.external_id
        image.url = image_payload.url
        image.name = image_payload.name
        image.alt_text = image_payload.alt_text
        image.sort_order = image_payload.sort_order
        if image.external_id:
            remote_changed = (
                prior_url != image.url
                or prior_name != image.name
                or prior_alt_text != image.alt_text
                or prior_sort_order != image.sort_order
                or not had_external_id
            )
            if remote_changed:
                image.sync_status = "pending_update"
            elif image.sync_status == "pending_remove":
                image.sync_status = "pending_update"
            elif image.sync_status not in {"pending_add", "pending_update"}:
                image.sync_status = "synced"
        else:
            image.sync_status = "pending_add"
        db.flush()
        keep_ids.add(image.id)

    for image_id, image in existing.items():
        if image_id not in keep_ids:
            if image.external_id:
                image.sync_status = "pending_remove"
            else:
                db.delete(image)


def replace_product_videos(
    db: Session,
    *,
    company_id: str,
    product: Product,
    videos: list[Any],
) -> None:
    if len(videos) > PRODUCT_VIDEO_MAX_COUNT:
        raise ServiceError(422, f"A product can have at most {PRODUCT_VIDEO_MAX_COUNT} videos.")
    existing = {
        video.id: video
        for video in db.scalars(select(ProductVideo).where(ProductVideo.product_id == product.id))
    }
    keep_ids: set[str] = set()
    for video_payload in videos:
        video_id = getattr(video_payload, "id", None)
        video = existing.get(video_id) if video_id else None
        if video is None:
            video = ProductVideo(
                company_id=company_id,
                product_id=product.id,
                source_type=product_video_source_type(video_payload.url),
                url=video_payload.url,
            )
            db.add(video)
        elif video.url != video_payload.url:
            previous_url = video.url
            previous_source_type = video.source_type
            video.url = video_payload.url
            video.source_type = product_video_source_type(video_payload.url)
            video.external_id = None
            video.remote_url = None
            video.last_synced_at = None
            video.sync_status = "pending_update"
            if previous_source_type == "uploaded":
                _remove_uploaded_product_video(previous_url)
        if video.name != video_payload.name or video.sort_order != video_payload.sort_order:
            if video.sync_status == "synced":
                video.sync_status = "pending_update"
        video.name = video_payload.name
        video.sort_order = video_payload.sort_order
        db.flush()
        keep_ids.add(video.id)

    for video_id, video in existing.items():
        if video_id not in keep_ids:
            if video.source_type == "uploaded":
                _remove_uploaded_product_video(video.url)
            db.delete(video)


def create_product(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    payload: ProductCreate,
) -> Product:
    scoped_company_id = require_company_id(company_id)
    category_ids = normalized_category_ids(payload.category_id, payload.category_ids)
    primary_category_id = payload.category_id or (category_ids[0] if category_ids else None)
    sku = payload.sku or generate_product_sku(db, scoped_company_id)
    barcode = payload.barcode or generate_product_barcode(db, scoped_company_id)
    validate_product_references(
        db,
        company_id=scoped_company_id,
        category_id=primary_category_id,
        brand_id=payload.brand_id,
        vendor_id=payload.vendor_id,
    )
    slug = normalize_slug(payload.name, payload.slug)
    ensure_unique_slug(db, Product, company_id=scoped_company_id, slug=slug)
    ensure_unique_sku(db, company_id=scoped_company_id, sku=sku)
    validate_variant_skus(
        db,
        company_id=scoped_company_id,
        product_sku=sku,
        variants=payload.variants,
    )
    for image in payload.images:
        if image.variant_id:
            raise ServiceError(422, "Product creation images cannot reference unsaved variants.")

    product = Product(
        company_id=scoped_company_id,
        category_id=primary_category_id,
        brand_id=payload.brand_id,
        vendor_id=payload.vendor_id,
        name=payload.name,
        slug=slug,
        sku=sku,
        barcode=barcode,
        product_type=validate_product_type(payload.product_type),
        status=validate_status(payload.status),
        description=payload.description,
        short_description=payload.short_description,
        seo_title=payload.seo_title,
        seo_description=payload.seo_description,
        visibility=payload.visibility,
        featured=payload.featured,
        global_unique_id=payload.global_unique_id,
        regular_price_minor=payload.regular_price_minor,
        sale_price_minor=payload.sale_price_minor,
        sale_start_at=payload.sale_start_at,
        sale_end_at=payload.sale_end_at,
        tax_status=payload.tax_status,
        tax_class=payload.tax_class,
        manage_stock=payload.manage_stock,
        stock_quantity=payload.stock_quantity,
        stock_status=payload.stock_status,
        backorders=payload.backorders,
        sold_individually=payload.sold_individually,
        weight=payload.weight,
        length=payload.length,
        width=payload.width,
        height=payload.height,
        shipping_class=payload.shipping_class,
        reviews_allowed=payload.reviews_allowed,
        purchase_note=payload.purchase_note,
        menu_order=payload.menu_order,
        attributes=payload.attributes,
        default_attributes=payload.default_attributes,
        custom_metadata=payload.custom_metadata,
        metadata_json=payload.metadata,
    )
    db.add(product)
    db.flush()

    replace_product_categories(
        db,
        company_id=scoped_company_id,
        product=product,
        category_ids=category_ids,
    )
    replace_product_tags(db, company_id=scoped_company_id, product=product, tags=payload.tags)
    for field_name, relationship_type in RELATIONSHIP_FIELDS.items():
        replace_product_relationships(
            db,
            company_id=scoped_company_id,
            product=product,
            relationship_type=relationship_type,
            target_ids=getattr(payload, field_name),
        )
    replace_product_variants(
        db,
        company_id=scoped_company_id,
        product=product,
        variants=payload.variants,
    )
    replace_product_images(
        db,
        company_id=scoped_company_id,
        product=product,
        images=payload.images,
    )
    replace_product_videos(
        db,
        company_id=scoped_company_id,
        product=product,
        videos=payload.videos,
    )
    db.flush()
    db.refresh(product)
    record_audit(
        db,
        action="catalog.product_created",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"name": product.name, "slug": product.slug, "sku": product.sku},
    )
    return product


def update_product(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    product_id: str,
    payload: ProductUpdate,
) -> Product:
    scoped_company_id = require_company_id(company_id)
    product = get_product(db, scoped_company_id, product_id)
    fields = payload.model_dump(exclude_unset=True)
    category_ids = fields.get("category_ids")
    next_category_id = fields.get("category_id", product.category_id)
    if category_ids is not None and "category_id" not in fields:
        next_category_id = category_ids[0] if category_ids else None
    validate_product_references(
        db,
        company_id=scoped_company_id,
        category_id=next_category_id,
        brand_id=fields.get("brand_id", product.brand_id),
        vendor_id=fields.get("vendor_id", product.vendor_id),
    )
    if "slug" in fields:
        product.slug = normalize_slug(fields.get("name") or product.name, fields["slug"])
        ensure_unique_slug(
            db,
            Product,
            company_id=scoped_company_id,
            slug=product.slug,
            exclude_id=product.id,
        )
    if "sku" in fields:
        ensure_unique_sku(
            db,
            company_id=scoped_company_id,
            sku=fields["sku"],
            exclude_product_id=product.id,
        )
    if "product_type" in fields and fields["product_type"] is not None:
        fields["product_type"] = validate_product_type(fields["product_type"])
    if "status" in fields and fields["status"] is not None:
        fields["status"] = validate_status(fields["status"])

    for field in (
        "name",
        "sku",
        "barcode",
        "product_type",
        "status",
        "category_id",
        "brand_id",
        "vendor_id",
        "description",
        "short_description",
        "seo_title",
        "seo_description",
        "visibility",
        "featured",
        "global_unique_id",
        "regular_price_minor",
        "sale_price_minor",
        "sale_start_at",
        "sale_end_at",
        "tax_status",
        "tax_class",
        "manage_stock",
        "stock_quantity",
        "stock_status",
        "backorders",
        "sold_individually",
        "weight",
        "length",
        "width",
        "height",
        "shipping_class",
        "reviews_allowed",
        "purchase_note",
        "menu_order",
        "attributes",
        "default_attributes",
        "custom_metadata",
    ):
        if field in fields:
            setattr(product, field, fields[field])
    if "metadata" in fields:
        product.metadata_json = fields["metadata"]

    if category_ids is not None:
        product.category_id = next_category_id
        replace_product_categories(
            db,
            company_id=scoped_company_id,
            product=product,
            category_ids=normalized_category_ids(product.category_id, category_ids),
        )
    elif "category_id" in fields:
        replace_product_categories(
            db,
            company_id=scoped_company_id,
            product=product,
            category_ids=normalized_category_ids(product.category_id, []),
        )
    if "tags" in fields and payload.tags is not None:
        replace_product_tags(db, company_id=scoped_company_id, product=product, tags=payload.tags)
    for field_name, relationship_type in RELATIONSHIP_FIELDS.items():
        values = getattr(payload, field_name)
        if field_name in fields and values is not None:
            replace_product_relationships(
                db,
                company_id=scoped_company_id,
                product=product,
                relationship_type=relationship_type,
                target_ids=values,
            )
    if "variants" in fields and payload.variants is not None:
        replace_product_variants(
            db,
            company_id=scoped_company_id,
            product=product,
            variants=payload.variants,
        )
    if "images" in fields and payload.images is not None:
        replace_product_images(
            db,
            company_id=scoped_company_id,
            product=product,
            images=payload.images,
        )
    if "videos" in fields and payload.videos is not None:
        replace_product_videos(
            db,
            company_id=scoped_company_id,
            product=product,
            videos=payload.videos,
        )
    db.flush()
    db.refresh(product)
    record_audit(
        db,
        action="catalog.product_updated",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"updated_fields": sorted(fields)},
    )
    return product


def archive_product(
    db: Session,
    *,
    company_id: str | None,
    user_id: str | None,
    product_id: str,
) -> None:
    scoped_company_id = require_company_id(company_id)
    product = get_product(db, scoped_company_id, product_id)
    product.status = "archived"
    record_audit(
        db,
        action="catalog.product_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"soft_delete": True},
    )


def permanently_delete_product(
    db: Session,
    *,
    company_id: str | None,
    user_id: str,
    product_id: str,
) -> None:
    scoped_company_id = require_company_id(company_id)
    product = get_product(db, scoped_company_id, product_id)
    if product.status != "archived":
        raise ServiceError(409, "Move the product to Trash before deleting it permanently.")

    variant_ids = list(
        db.scalars(
            select(ProductVariant.id).where(
                ProductVariant.company_id == scoped_company_id,
                ProductVariant.product_id == product.id,
            )
        )
    )

    protected_references = []
    if db.scalar(
        select(MarketplaceCommissionRule.id)
        .where(
            MarketplaceCommissionRule.company_id == scoped_company_id,
            MarketplaceCommissionRule.product_id == product.id,
        )
        .limit(1)
    ):
        protected_references.append("commission rules")
    if db.scalar(
        select(StockMovement.id)
        .where(
            StockMovement.company_id == scoped_company_id,
            StockMovement.product_id == product.id,
        )
        .limit(1)
    ):
        protected_references.append("stock history")
    if db.scalar(
        select(OrderItem.id)
        .where(OrderItem.company_id == scoped_company_id, OrderItem.product_id == product.id)
        .limit(1)
    ):
        protected_references.append("orders")
    if db.scalar(
        select(VendorOrderItem.id)
        .where(
            VendorOrderItem.company_id == scoped_company_id,
            VendorOrderItem.product_id == product.id,
        )
        .limit(1)
    ):
        protected_references.append("vendor order items")
    if table_exists(db, "vendor_inventory_balances") and db.scalar(
        select(VendorInventoryBalance.id)
        .where(
            VendorInventoryBalance.company_id == scoped_company_id,
            VendorInventoryBalance.product_id == product.id,
        )
        .limit(1)
    ):
        protected_references.append("vendor inventory balances")
    if table_exists(db, "vendor_inventory_movements") and db.scalar(
        select(VendorInventoryMovement.id)
        .where(
            VendorInventoryMovement.company_id == scoped_company_id,
            VendorInventoryMovement.product_id == product.id,
        )
        .limit(1)
    ):
        protected_references.append("vendor inventory movements")

    if protected_references:
        references = ", ".join(protected_references)
        raise ServiceError(
            409,
            f"Product cannot be deleted permanently because it has {references}.",
        )

    db.query(SyncConflict).filter(
        SyncConflict.company_id == scoped_company_id,
        SyncConflict.connector == "woocommerce",
        SyncConflict.resource_type == "product",
        SyncConflict.resource_id == product.id,
    ).delete(synchronize_session=False)
    db.query(SyncOutbox).filter(
        SyncOutbox.company_id == scoped_company_id,
        SyncOutbox.resource_type == "product",
        SyncOutbox.resource_id == product.id,
    ).delete(synchronize_session=False)
    db.query(ExternalResourceMap).filter(
        ExternalResourceMap.company_id == scoped_company_id,
        ExternalResourceMap.internal_resource_type == "product",
        ExternalResourceMap.internal_resource_id == product.id,
    ).delete(synchronize_session=False)
    db.query(ProductImage).filter(ProductImage.product_id == product.id).delete(
        synchronize_session=False
    )
    for video in product_videos(db, product.id):
        if video.source_type == "uploaded":
            _remove_uploaded_product_video(video.url)
    db.query(ProductVideo).filter(ProductVideo.product_id == product.id).delete(
        synchronize_session=False
    )
    db.query(ProductCategoryLink).filter(ProductCategoryLink.product_id == product.id).delete(
        synchronize_session=False
    )
    db.query(ProductTagLink).filter(ProductTagLink.product_id == product.id).delete(
        synchronize_session=False
    )
    db.query(ProductRelationship).filter(
        ProductRelationship.source_product_id == product.id
    ).delete(synchronize_session=False)
    db.query(ProductRelationship).filter(
        ProductRelationship.target_product_id == product.id
    ).delete(synchronize_session=False)
    db.query(VendorProduct).filter(
        VendorProduct.company_id == scoped_company_id,
        VendorProduct.product_id == product.id,
    ).delete(synchronize_session=False)
    if variant_ids:
        db.query(SyncOutbox).filter(
            SyncOutbox.company_id == scoped_company_id,
            SyncOutbox.resource_id.in_(variant_ids),
        ).delete(synchronize_session=False)
    db.query(ProductVariant).filter(ProductVariant.product_id == product.id).delete(
        synchronize_session=False
    )
    db.delete(product)
    record_audit(
        db,
        action="catalog.product_permanently_deleted",
        company_id=scoped_company_id,
        user_id=user_id,
        entity_type="product",
        entity_id=product.id,
        metadata={"name": product.name, "sku": product.sku},
    )
