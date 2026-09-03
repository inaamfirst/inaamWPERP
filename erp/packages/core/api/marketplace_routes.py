from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erp.packages.core import marketplace_services
from erp.packages.core.api.dependencies import DbSession, require_permission, service_error_to_http
from erp.packages.core.api.serializers import product_out
from erp.packages.core.auth_delivery import deliver_action_token
from erp.packages.core.catalog_services import (
    archive_product,
    create_brand,
    create_category,
    list_brands,
    list_categories,
    permanently_delete_product,
)
from erp.packages.core.config import get_settings
from erp.packages.core.db.models import Brand, Category, ProductImage, ProductVideo, Role, UserRole
from erp.packages.core.schemas import (
    AdminVendorAccountCreate,
    AdminVendorAccountOut,
    BrandCreate,
    BrandOut,
    CategoryCreate,
    CategoryOut,
    CommissionRuleCreate,
    CommissionRuleOut,
    CommissionRuleUpdate,
    ProductCreate,
    ProductImageOut,
    ProductOut,
    ProductUpdate,
    ProductVideoOut,
    StatusChangeRequest,
    UserOut,
    VendorCreate,
    VendorLifecycleRequest,
    VendorNotificationOut,
    VendorOrderItemOut,
    VendorOrderItemStatusChange,
    VendorOrderItemStatusHistoryOut,
    VendorOut,
    VendorProductAssignRequest,
    VendorProductOut,
    VendorSettlementCreate,
    VendorSettlementOut,
    VendorUpdate,
    VendorUserCreate,
    VendorUserOut,
)
from erp.packages.core.services import AuthContext, ServiceError
from erp.packages.core.vendor_auth_services import (
    change_vendor_status,
    create_admin_vendor_account,
)
from erp.packages.core.woocommerce_services import (
    enqueue_product_sync,
    enqueue_product_video_sync,
    load_woocommerce_config,
    saved_wordpress_video_plugin_status,
)

router = APIRouter()

PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PRODUCT_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
PRODUCT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
PRODUCT_VIDEO_EXTENSION = ".mp4"
PRODUCT_VIDEO_MIME_TYPES = {"video/mp4", "application/mp4"}
PRODUCT_VIDEO_MAX_BYTES = 100 * 1024 * 1024
PRODUCT_VIDEO_MAX_COUNT = 10

VendorViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.view")),
]
VendorManageContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.manage")),
]
VendorUsersManageContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.users.manage")),
]
VendorProductsManageContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.products.manage")),
]
VendorOrdersViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.orders.view")),
]
VendorSettleContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.settle")),
]
VendorCommissionContext = Annotated[
    AuthContext,
    Depends(require_permission("vendors.commissions.manage")),
]
VendorProfileViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.profile.view")),
]
VendorProductsViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.products.view")),
]
VendorProductsSelfManageContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.products.manage")),
]
VendorOrdersSelfViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.orders.view")),
]
VendorOrdersSelfManageContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.orders.manage")),
]
VendorSettlementsSelfViewContext = Annotated[
    AuthContext,
    Depends(require_permission("vendor.settlements.view")),
]
PageOffset = Annotated[int, Query(ge=0)]
PageLimit = Annotated[int, Query(ge=1, le=500)]


def _company_id(context: AuthContext) -> str:
    if not context.user.company_id:
        raise ServiceError(403, "A company-scoped user is required.")
    return context.user.company_id


def _current_vendor(db: Session, context: AuthContext):
    company_id = _company_id(context)
    return marketplace_services.vendor_for_user(db, company_id, context.user.id)


def _enqueue_product_sync_if_configured(db: Session, company_id: str, product) -> None:
    try:
        enqueue_product_sync(db, company_id=company_id, product=product)
    except ServiceError as exc:
        if exc.status_code == 404 and exc.message == "WooCommerce is not configured.":
            return
        raise


def _enqueue_product_video_sync_if_configured(db: Session, company_id: str, product) -> None:
    if load_woocommerce_config(db, company_id) is not None:
        enqueue_product_video_sync(db, company_id=company_id, product=product)


def _effective_product_video_upload_limit(db: Session, company_id: str) -> tuple[int, bool]:
    remote_limit = saved_wordpress_video_plugin_status(db, company_id).get("max_upload_bytes")
    try:
        remote_limit_bytes = int(remote_limit) if remote_limit is not None else 0
    except (TypeError, ValueError):
        remote_limit_bytes = 0
    if remote_limit_bytes > 0 and remote_limit_bytes < PRODUCT_VIDEO_MAX_BYTES:
        return remote_limit_bytes, True
    return PRODUCT_VIDEO_MAX_BYTES, False


def _product_video_upload_limit_error(limit_bytes: int, is_wordpress_limit: bool) -> ServiceError:
    if not is_wordpress_limit:
        return ServiceError(413, "Product video is too large.")
    limit_label = (
        f"{limit_bytes // (1024 * 1024)} MB"
        if limit_bytes >= 1024 * 1024
        else f"{limit_bytes} bytes"
    )
    return ServiceError(413, f"Product video exceeds the WordPress upload limit ({limit_label}).")


def _category_out(category: Category) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        company_id=category.company_id,
        parent_id=category.parent_id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        is_active=category.is_active,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def _brand_out(brand: Brand) -> BrandOut:
    return BrandOut(
        id=brand.id,
        company_id=brand.company_id,
        name=brand.name,
        slug=brand.slug,
        description=brand.description,
        is_active=brand.is_active,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


def _user_out(user, db: Session) -> UserOut:
    roles = list(
        db.query(Role.id, Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id, Role.company_id == user.company_id)
        .order_by(Role.name, Role.id)
        .all()
    )
    return UserOut(
        id=user.id,
        company_id=user.company_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        account_status=user.account_status,
        must_change_password=user.must_change_password,
        password_changed_at=user.password_changed_at,
        last_login_at=user.last_login_at,
        role_ids=[str(role_id) for role_id, _role_name in roles],
        role_names=[str(role_name) for _role_id, role_name in roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/marketplace/vendors", response_model=list[VendorOut], tags=["marketplace"])
def vendors_list(
    context: VendorViewContext,
    db: DbSession,
    status: str | None = None,
) -> list[VendorOut]:
    try:
        return [
            marketplace_services.vendor_out(vendor)
            for vendor in marketplace_services.list_vendors(
                db,
                context.user.company_id,
                status=status,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors",
    response_model=VendorOut,
    status_code=201,
    tags=["marketplace"],
)
def vendor_create(
    payload: VendorCreate,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        vendor = marketplace_services.create_vendor(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_out(vendor)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/with-account",
    response_model=AdminVendorAccountOut,
    status_code=201,
    tags=["marketplace"],
)
def vendor_account_create(
    payload: AdminVendorAccountCreate,
    request: Request,
    context: VendorManageContext,
    db: DbSession,
) -> AdminVendorAccountOut:
    try:
        company_id = _company_id(context)
        created = create_admin_vendor_account(
            db,
            company_id=company_id,
            actor_user_id=context.user.id,
            payload=payload,
        )
        activation_delivery = "not_requested"
        if created.activation_token:
            delivered = deliver_action_token(
                email=created.user.email or "",
                purpose="activation",
                token=created.activation_token,
                settings=request.app.state.settings,
            )
            if not delivered:
                raise ServiceError(503, "Activation delivery is not configured.")
            activation_delivery = "sent"
        db.commit()
        return AdminVendorAccountOut(
            vendor=marketplace_services.vendor_out(created.vendor),
            user=_user_out(created.user, db),
            activation_token=None,
            activation_expires_at=created.activation_expires_at,
            onboarding_method=("activation" if payload.use_activation else "temporary_password"),
            activation_delivery=activation_delivery,
        )
    except (OSError, ServiceError) as exc:
        db.rollback()
        if isinstance(exc, ServiceError):
            raise service_error_to_http(exc) from exc
        error = ServiceError(503, "Activation delivery failed.")
        raise service_error_to_http(error) from exc
    except IntegrityError as exc:
        db.rollback()
        error = ServiceError(409, "Vendor account could not be created.")
        raise service_error_to_http(error) from exc


@router.get("/marketplace/vendors/{vendor_id}", response_model=VendorOut, tags=["marketplace"])
def vendor_detail(
    vendor_id: str,
    context: VendorViewContext,
    db: DbSession,
) -> VendorOut:
    try:
        return marketplace_services.vendor_out(
            marketplace_services.get_vendor(db, context.user.company_id, vendor_id)
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.put(
    "/marketplace/vendors/{vendor_id}",
    response_model=VendorOut,
    status_code=200,
    tags=["marketplace"],
)
def vendor_update(
    vendor_id: str,
    payload: VendorUpdate,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        vendor = marketplace_services.update_vendor(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=vendor_id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_out(vendor)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/{vendor_id}/approve",
    response_model=VendorOut,
    tags=["marketplace"],
)
def vendor_approve(
    vendor_id: str,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        vendor = marketplace_services.approve_vendor(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=vendor_id,
        )
        db.commit()
        return marketplace_services.vendor_out(vendor)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.patch(
    "/marketplace/vendors/{vendor_id}/status",
    response_model=VendorOut,
    tags=["marketplace"],
)
def vendor_status_change(
    vendor_id: str,
    payload: StatusChangeRequest,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        vendor = change_vendor_status(
            db,
            company_id=_company_id(context),
            actor_user_id=context.user.id,
            vendor_id=vendor_id,
            status=payload.status,
            reason=payload.reason,
        )
        db.commit()
        return marketplace_services.vendor_out(vendor)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


def _vendor_lifecycle_transition(
    *,
    db: Session,
    context: AuthContext,
    vendor_id: str,
    status: str,
    reason: str | None,
) -> VendorOut:
    vendor = change_vendor_status(
        db,
        company_id=_company_id(context),
        actor_user_id=context.user.id,
        vendor_id=vendor_id,
        status=status,
        reason=reason,
    )
    db.commit()
    return marketplace_services.vendor_out(vendor)


@router.post(
    "/marketplace/vendors/{vendor_id}/pause",
    response_model=VendorOut,
    tags=["marketplace"],
)
def vendor_pause(
    vendor_id: str,
    payload: VendorLifecycleRequest,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        return _vendor_lifecycle_transition(
            db=db,
            context=context,
            vendor_id=vendor_id,
            status="paused",
            reason=payload.reason,
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/{vendor_id}/reactivate",
    response_model=VendorOut,
    tags=["marketplace"],
)
def vendor_reactivate(
    vendor_id: str,
    payload: VendorLifecycleRequest,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        return _vendor_lifecycle_transition(
            db=db,
            context=context,
            vendor_id=vendor_id,
            status="active",
            reason=payload.reason,
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/{vendor_id}/stop",
    response_model=VendorOut,
    tags=["marketplace"],
)
def vendor_stop(
    vendor_id: str,
    payload: VendorLifecycleRequest,
    context: VendorManageContext,
    db: DbSession,
) -> VendorOut:
    try:
        return _vendor_lifecycle_transition(
            db=db,
            context=context,
            vendor_id=vendor_id,
            status="stopped",
            reason=payload.reason,
        )
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendors/{vendor_id}/users",
    response_model=list[VendorUserOut],
    tags=["marketplace"],
)
def vendor_users_list(
    vendor_id: str,
    context: VendorUsersManageContext,
    db: DbSession,
) -> list[VendorUserOut]:
    try:
        return [
            marketplace_services.vendor_user_out(vendor_user)
            for vendor_user in marketplace_services.list_vendor_users(
                db,
                context.user.company_id,
                vendor_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/{vendor_id}/users",
    response_model=VendorUserOut,
    status_code=201,
    tags=["marketplace"],
)
def vendor_user_create(
    vendor_id: str,
    payload: VendorUserCreate,
    context: VendorUsersManageContext,
    db: DbSession,
) -> VendorUserOut:
    try:
        vendor_user = marketplace_services.add_vendor_user(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=vendor_id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_user_out(vendor_user)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendors/{vendor_id}/products",
    response_model=list[VendorProductOut],
    tags=["marketplace"],
)
def vendor_products_list(
    vendor_id: str,
    context: VendorViewContext,
    db: DbSession,
) -> list[VendorProductOut]:
    try:
        return [
            marketplace_services.vendor_product_out(row)
            for row in marketplace_services.list_vendor_products(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendor/products",
    response_model=list[VendorProductOut],
    tags=["marketplace"],
)
@router.get(
    "/vendor/products",
    response_model=list[VendorProductOut],
    tags=["marketplace"],
)
def current_vendor_products(
    context: VendorProductsViewContext,
    db: DbSession,
) -> list[VendorProductOut]:
    try:
        vendor = _current_vendor(db, context)
        return [
            marketplace_services.vendor_product_out(row)
            for row in marketplace_services.list_vendor_products(
                db,
                context.user.company_id,
                vendor_id=vendor.id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/vendor/catalog/categories", response_model=list[CategoryOut], tags=["vendor"])
def current_vendor_catalog_categories(
    context: VendorProductsViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[CategoryOut]:
    try:
        return [
            _category_out(category)
            for category in list_categories(
                db, _company_id(context), include_archived=include_archived
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/vendor/catalog/categories",
    response_model=CategoryOut,
    status_code=201,
    tags=["vendor"],
)
def current_vendor_catalog_category_create(
    payload: CategoryCreate,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> CategoryOut:
    try:
        category = create_category(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return _category_out(category)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/vendor/catalog/brands", response_model=list[BrandOut], tags=["vendor"])
def current_vendor_catalog_brands(
    context: VendorProductsViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[BrandOut]:
    try:
        return [
            _brand_out(brand)
            for brand in list_brands(
                db, _company_id(context), include_archived=include_archived
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post("/vendor/catalog/brands", response_model=BrandOut, status_code=201, tags=["vendor"])
def current_vendor_catalog_brand_create(
    payload: BrandCreate,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> BrandOut:
    try:
        brand = create_brand(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return _brand_out(brand)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get("/vendor/catalog/products", response_model=list[ProductOut], tags=["vendor"])
def current_vendor_catalog_products(
    context: VendorProductsViewContext,
    db: DbSession,
    include_archived: bool = False,
) -> list[ProductOut]:
    try:
        vendor = _current_vendor(db, context)
        from erp.packages.core.catalog_services import list_products

        return [
            product_out(db, product)
            for product in list_products(
                db, context.user.company_id, include_archived=include_archived
            )
            if product.vendor_id == vendor.id
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get("/vendor/catalog/products/{product_id}", response_model=ProductOut, tags=["vendor"])
def current_vendor_catalog_product_detail(
    product_id: str,
    context: VendorProductsViewContext,
    db: DbSession,
) -> ProductOut:
    try:
        vendor = _current_vendor(db, context)
        product = marketplace_services.vendor_owned_product(
            db, _company_id(context), vendor.id, product_id
        )
        return product_out(db, product)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/vendor/catalog/products", response_model=ProductOut, status_code=201, tags=["vendor"]
)
def current_vendor_catalog_product_create(
    payload: ProductCreate,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> ProductOut:
    try:
        vendor = _current_vendor(db, context)
        product = marketplace_services.create_vendor_product(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            vendor_id=vendor.id,
            payload=payload,
        )
        _enqueue_product_sync_if_configured(db, _company_id(context), product)
        db.commit()
        return product_out(db, product)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/vendor/catalog/products/{product_id}/images/upload",
    response_model=ProductImageOut,
    status_code=201,
    tags=["vendor"],
)
def current_vendor_catalog_product_image_upload(
    product_id: str,
    context: VendorProductsSelfManageContext,
    db: DbSession,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> ProductImageOut:
    target_path: Path | None = None
    try:
        vendor = _current_vendor(db, context)
        product = marketplace_services.vendor_owned_product(
            db, _company_id(context), vendor.id, product_id
        )
        original_name = Path(file.filename or "product-image").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in PRODUCT_IMAGE_EXTENSIONS:
            raise ServiceError(422, "Unsupported image extension.")
        content_type = (file.content_type or mimetypes.types_map.get(suffix) or "").lower()
        if content_type not in PRODUCT_IMAGE_MIME_TYPES:
            raise ServiceError(422, "Unsupported image content type.")

        settings = getattr(request.app.state, "settings", get_settings())
        relative_dir = Path("products") / product.company_id / product.id
        target_dir = Path(settings.media_upload_dir) / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{uuid.uuid4().hex}{suffix}"
        target_path = target_dir / target_name

        size = 0
        with target_path.open("wb") as handle:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > PRODUCT_IMAGE_MAX_BYTES:
                    raise ServiceError(413, "Product image is too large.")
                handle.write(chunk)

        image_count = db.query(ProductImage).filter(ProductImage.product_id == product.id).count()
        image = ProductImage(
            company_id=product.company_id,
            product_id=product.id,
            url=f"/media/{relative_dir.as_posix()}/{target_name}",
            name=original_name[:255],
            alt_text=product.name,
            sort_order=image_count,
            sync_status="pending_add",
        )
        db.add(image)
        _enqueue_product_sync_if_configured(db, _company_id(context), product)
        db.commit()
        db.refresh(image)
        return ProductImageOut(
            id=image.id,
            product_id=image.product_id,
            variant_id=image.variant_id,
            external_id=image.external_id,
            url=image.url,
            name=image.name,
            alt_text=image.alt_text,
            sort_order=image.sort_order,
            sync_status=image.sync_status,
            last_synced_at=image.last_synced_at,
        )
    except ServiceError as exc:
        db.rollback()
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        raise service_error_to_http(exc) from exc


@router.post(
    "/vendor/catalog/products/{product_id}/videos/upload",
    response_model=ProductVideoOut,
    status_code=201,
    tags=["vendor"],
)
def current_vendor_catalog_product_video_upload(
    product_id: str,
    context: VendorProductsSelfManageContext,
    db: DbSession,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> ProductVideoOut:
    target_path: Path | None = None
    try:
        vendor = _current_vendor(db, context)
        product = marketplace_services.vendor_owned_product(
            db, _company_id(context), vendor.id, product_id
        )
        video_count = db.query(ProductVideo).filter(ProductVideo.product_id == product.id).count()
        if video_count >= PRODUCT_VIDEO_MAX_COUNT:
            raise ServiceError(422, f"A product can have at most {PRODUCT_VIDEO_MAX_COUNT} videos.")
        original_name = Path(file.filename or "product-video.mp4").name
        suffix = Path(original_name).suffix.lower()
        if suffix != PRODUCT_VIDEO_EXTENSION:
            raise ServiceError(422, "Unsupported video extension. Only MP4 files are allowed.")
        content_type = (file.content_type or mimetypes.types_map.get(suffix) or "").lower()
        if content_type not in PRODUCT_VIDEO_MIME_TYPES:
            raise ServiceError(422, "Unsupported video content type. Only MP4 files are allowed.")
        upload_limit, is_wordpress_limit = _effective_product_video_upload_limit(
            db, _company_id(context)
        )

        settings = getattr(request.app.state, "settings", get_settings())
        relative_dir = Path("products") / product.company_id / product.id / "videos"
        target_dir = Path(settings.media_upload_dir) / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{uuid.uuid4().hex}{suffix}"
        target_path = target_dir / target_name
        size = 0
        with target_path.open("wb") as handle:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > upload_limit:
                    raise _product_video_upload_limit_error(upload_limit, is_wordpress_limit)
                handle.write(chunk)

        video = ProductVideo(
            company_id=product.company_id,
            product_id=product.id,
            source_type="uploaded",
            url=f"/media/{relative_dir.as_posix()}/{target_name}",
            name=original_name[:255],
            sort_order=video_count,
        )
        db.add(video)
        db.flush()
        _enqueue_product_video_sync_if_configured(db, _company_id(context), product)
        db.commit()
        db.refresh(video)
        return ProductVideoOut(
            id=video.id,
            product_id=video.product_id,
            source_type=video.source_type,
            url=video.url,
            name=video.name,
            sort_order=video.sort_order,
            external_id=video.external_id,
            remote_url=video.remote_url,
            sync_status=video.sync_status,
            last_synced_at=video.last_synced_at,
            created_at=video.created_at,
            updated_at=video.updated_at,
        )
    except ServiceError as exc:
        db.rollback()
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        raise service_error_to_http(exc) from exc


@router.patch("/vendor/catalog/products/{product_id}", response_model=ProductOut, tags=["vendor"])
def current_vendor_catalog_product_update(
    product_id: str,
    payload: ProductUpdate,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> ProductOut:
    try:
        vendor = _current_vendor(db, context)
        product = marketplace_services.update_vendor_product(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            vendor_id=vendor.id,
            product_id=product_id,
            payload=payload,
        )
        if set(payload.model_fields_set) == {"videos"}:
            _enqueue_product_video_sync_if_configured(db, _company_id(context), product)
        else:
            _enqueue_product_sync_if_configured(db, _company_id(context), product)
        db.commit()
        return product_out(db, product)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/vendor/catalog/products/{product_id}", status_code=200, tags=["vendor"])
def current_vendor_catalog_product_archive(
    product_id: str,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        vendor = _current_vendor(db, context)
        marketplace_services.vendor_owned_product(db, _company_id(context), vendor.id, product_id)
        archive_product(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            product_id=product_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.delete("/vendor/catalog/products/{product_id}/permanent", status_code=200, tags=["vendor"])
def current_vendor_catalog_product_permanent_delete(
    product_id: str,
    context: VendorProductsSelfManageContext,
    db: DbSession,
) -> dict[str, bool]:
    try:
        vendor = _current_vendor(db, context)
        marketplace_services.vendor_owned_product(db, _company_id(context), vendor.id, product_id)
        permanently_delete_product(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            product_id=product_id,
        )
        db.commit()
        return {"ok": True}
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/vendor/order-items/{vendor_order_item_id}/status",
    response_model=VendorOrderItemOut,
    tags=["vendor"],
)
def current_vendor_order_item_status_update(
    vendor_order_item_id: str,
    payload: VendorOrderItemStatusChange,
    context: VendorOrdersSelfManageContext,
    db: DbSession,
) -> VendorOrderItemOut:
    try:
        vendor = _current_vendor(db, context)
        item = marketplace_services.change_vendor_order_item_status(
            db,
            company_id=_company_id(context),
            user_id=context.user.id,
            vendor_id=vendor.id,
            vendor_order_item_id=vendor_order_item_id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_order_item_out(item, db=db)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/vendor/order-items/{vendor_order_item_id}/history",
    response_model=list[VendorOrderItemStatusHistoryOut],
    tags=["vendor"],
)
def current_vendor_order_item_history(
    vendor_order_item_id: str,
    context: VendorOrdersSelfViewContext,
    db: DbSession,
) -> list[VendorOrderItemStatusHistoryOut]:
    try:
        vendor = _current_vendor(db, context)
        return [
            VendorOrderItemStatusHistoryOut(
                id=row.id,
                vendor_order_item_id=row.vendor_order_item_id,
                vendor_id=row.vendor_id,
                from_status=row.from_status,
                to_status=row.to_status,
                changed_by_id=row.changed_by_id,
                reason=row.reason,
                created_at=row.created_at,
            )
            for row in marketplace_services.vendor_order_item_status_history(
                db, _company_id(context), vendor.id, vendor_order_item_id
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendor-products/assign",
    response_model=VendorProductOut,
    status_code=201,
    tags=["marketplace"],
)
def vendor_product_assign(
    payload: VendorProductAssignRequest,
    context: VendorProductsManageContext,
    db: DbSession,
) -> VendorProductOut:
    try:
        assignment = marketplace_services.assign_product_to_vendor(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_product_out(assignment)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/vendors/{vendor_id}/products/{product_id}/approve",
    response_model=VendorProductOut,
    tags=["marketplace"],
)
def vendor_product_approve(
    vendor_id: str,
    product_id: str,
    context: VendorProductsManageContext,
    db: DbSession,
) -> VendorProductOut:
    try:
        assignment = marketplace_services.approve_vendor_product(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            vendor_id=vendor_id,
            product_id=product_id,
        )
        db.commit()
        return marketplace_services.vendor_product_out(assignment)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/commission-rules",
    response_model=list[CommissionRuleOut],
    tags=["marketplace"],
)
def commission_rules_list(
    context: VendorViewContext,
    db: DbSession,
    vendor_id: str | None = None,
) -> list[CommissionRuleOut]:
    try:
        return [
            marketplace_services.commission_rule_out(rule)
            for rule in marketplace_services.list_commission_rules(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/commission-rules",
    response_model=CommissionRuleOut,
    status_code=201,
    tags=["marketplace"],
)
def commission_rule_create(
    payload: CommissionRuleCreate,
    context: VendorCommissionContext,
    db: DbSession,
) -> CommissionRuleOut:
    try:
        rule = marketplace_services.create_commission_rule(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.commission_rule_out(rule)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.put(
    "/marketplace/commission-rules/{rule_id}",
    response_model=CommissionRuleOut,
    status_code=200,
    tags=["marketplace"],
)
def commission_rule_update(
    rule_id: str,
    payload: CommissionRuleUpdate,
    context: VendorCommissionContext,
    db: DbSession,
) -> CommissionRuleOut:
    try:
        rule = marketplace_services.update_commission_rule(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            rule_id=rule_id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.commission_rule_out(rule)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendors/{vendor_id}/order-items",
    response_model=list[VendorOrderItemOut],
    tags=["marketplace"],
)
def vendor_order_items_list(
    vendor_id: str,
    context: VendorOrdersViewContext,
    db: DbSession,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorOrderItemOut]:
    try:
        return [
            marketplace_services.vendor_order_item_out(item, db=db)
            for item in marketplace_services.list_vendor_order_items(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
                status=status,
                order_status=order_status,
                payment_status=payment_status,
                settlement_id=settlement_id,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendor/orders",
    response_model=list[VendorOrderItemOut],
    tags=["marketplace"],
)
@router.get(
    "/vendor/orders",
    response_model=list[VendorOrderItemOut],
    tags=["marketplace"],
)
def current_vendor_orders(
    context: VendorOrdersSelfViewContext,
    db: DbSession,
    status: str | None = None,
    order_status: str | None = None,
    payment_status: str | None = None,
    settlement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorOrderItemOut]:
    try:
        vendor = _current_vendor(db, context)
        return [
            marketplace_services.vendor_order_item_out(item, db=db)
            for item in marketplace_services.list_vendor_order_items(
                db,
                context.user.company_id,
                vendor_id=vendor.id,
                status=status,
                order_status=order_status,
                payment_status=payment_status,
                settlement_id=settlement_id,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendors/{vendor_id}/settlements",
    response_model=list[VendorSettlementOut],
    tags=["marketplace"],
)
def vendor_settlements_list(
    vendor_id: str,
    context: VendorSettleContext,
    db: DbSession,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorSettlementOut]:
    try:
        return [
            marketplace_services.vendor_settlement_out(settlement)
            for settlement in marketplace_services.list_vendor_settlements(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendor/settlements",
    response_model=list[VendorSettlementOut],
    tags=["marketplace"],
)
@router.get(
    "/vendor/settlements",
    response_model=list[VendorSettlementOut],
    tags=["marketplace"],
)
def current_vendor_settlements(
    context: VendorSettlementsSelfViewContext,
    db: DbSession,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> list[VendorSettlementOut]:
    try:
        vendor = _current_vendor(db, context)
        return [
            marketplace_services.vendor_settlement_out(settlement)
            for settlement in marketplace_services.list_vendor_settlements(
                db,
                context.user.company_id,
                vendor_id=vendor.id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=limit,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.post(
    "/marketplace/settlements",
    response_model=VendorSettlementOut,
    status_code=201,
    tags=["marketplace"],
)
def vendor_settlement_create(
    payload: VendorSettlementCreate,
    context: VendorSettleContext,
    db: DbSession,
) -> VendorSettlementOut:
    try:
        settlement = marketplace_services.create_vendor_settlement(
            db,
            company_id=context.user.company_id,
            user_id=context.user.id,
            payload=payload,
        )
        db.commit()
        return marketplace_services.vendor_settlement_out(settlement)
    except ServiceError as exc:
        db.rollback()
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendors/{vendor_id}/notifications",
    response_model=list[VendorNotificationOut],
    tags=["marketplace"],
)
def vendor_notifications_list(
    vendor_id: str,
    context: VendorViewContext,
    db: DbSession,
) -> list[VendorNotificationOut]:
    try:
        return [
            marketplace_services.vendor_notification_out(notification)
            for notification in marketplace_services.list_vendor_notifications(
                db,
                context.user.company_id,
                vendor_id=vendor_id,
            )
        ]
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendor/me",
    response_model=VendorOut,
    tags=["marketplace"],
)
@router.get(
    "/vendor/me",
    response_model=VendorOut,
    tags=["marketplace"],
)
def current_vendor_detail(
    context: VendorProfileViewContext,
    db: DbSession,
) -> VendorOut:
    try:
        vendor = _current_vendor(db, context)
        return marketplace_services.vendor_out(vendor)
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc


@router.get(
    "/marketplace/vendor/dashboard",
    response_model=dict[str, object],
    tags=["marketplace"],
)
@router.get(
    "/vendor/dashboard",
    response_model=dict[str, object],
    tags=["marketplace"],
)
def current_vendor_dashboard(
    context: VendorProfileViewContext,
    db: DbSession,
) -> dict[str, object]:
    try:
        vendor = _current_vendor(db, context)
        return marketplace_services.vendor_dashboard_summary(
            db,
            context.user.company_id,
            vendor.id,
        )
    except ServiceError as exc:
        raise service_error_to_http(exc) from exc
