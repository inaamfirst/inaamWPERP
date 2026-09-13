"""Add vendor shop/POS ownership and controlled publication.

Revision ID: 202609100028
Revises: 202609100027
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "202609100028"
down_revision = "202609100027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("warehouses", sa.Column("vendor_id", sa.String(length=36), nullable=True))
    op.add_column("warehouses", sa.Column("warehouse_type", sa.String(length=40), nullable=False, server_default="company"))
    op.create_table(
        "shop_suppliers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255)), sa.Column("email", sa.String(length=255)),
        sa.Column("phone", sa.String(length=80)), sa.Column("address", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("company_id", "vendor_id", "name"),
    )
    op.create_table(
        "shop_purchases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), sa.ForeignKey("shop_suppliers.id"), nullable=False),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("purchase_number", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("payment_status", sa.String(length=40), nullable=False, server_default="unpaid"),
        sa.Column("total_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_minor", sa.Integer(), nullable=False, server_default="0"), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("company_id", "vendor_id", "purchase_number"),
    )
    op.create_table(
        "shop_purchase_lines", sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("purchase_id", sa.String(length=36), sa.ForeignKey("shop_purchases.id"), nullable=False),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", sa.String(length=36), sa.ForeignKey("product_variants.id")),
        sa.Column("quantity", sa.Integer(), nullable=False), sa.Column("unit_cost_minor", sa.Integer(), nullable=False),
        sa.Column("line_total_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "shop_finance_entries", sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("entry_type", sa.String(length=40), nullable=False), sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False), sa.Column("currency", sa.String(length=3), nullable=False, server_default="PKR"),
        sa.Column("source_type", sa.String(length=80), nullable=False), sa.Column("source_id", sa.String(length=120), nullable=False), sa.Column("memo", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_shop_finance_vendor_created", "shop_finance_entries", ["company_id", "vendor_id", "created_at"])
    bind = op.get_bind()
    permissions = sa.table("permissions", sa.column("id", sa.String), sa.column("key", sa.String), sa.column("description", sa.String))
    for key in ("vendor.shop.purchases.manage", "vendor.shop.accounting.view"):
        permission_id = bind.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if permission_id is None:
            permission_id = str(uuid.uuid4())
            bind.execute(sa.insert(permissions).values(id=permission_id, key=key, description=f"Permission: {key}"))
    listing = sa.table("product_channel_listings", sa.column("id", sa.String), sa.column("company_id", sa.String), sa.column("product_id", sa.String), sa.column("vendor_id", sa.String), sa.column("channel", sa.String), sa.column("listing_status", sa.String), sa.column("sync_status", sa.String), sa.column("metadata", sa.JSON))
    mappings = bind.execute(sa.text("SELECT company_id, internal_resource_id FROM external_resource_map WHERE connector = 'woocommerce' AND internal_resource_type = 'product'"))
    for company_id, product_id in mappings:
        exists = bind.execute(sa.select(listing.c.id).where(listing.c.company_id == company_id, listing.c.product_id == product_id, listing.c.channel == "woocommerce")).scalar()
        if not exists:
            vendor_id = bind.execute(sa.text("SELECT vendor_id FROM products WHERE id = :id"), {"id": product_id}).scalar()
            bind.execute(sa.insert(listing).values(id=str(uuid.uuid4()), company_id=company_id, product_id=product_id, vendor_id=vendor_id, channel="woocommerce", listing_status="published", sync_status="synced", metadata={}))


def downgrade() -> None:
    op.drop_index("ix_shop_finance_vendor_created", table_name="shop_finance_entries")
    op.drop_table("shop_finance_entries"); op.drop_table("shop_purchase_lines"); op.drop_table("shop_purchases"); op.drop_table("shop_suppliers")
    op.drop_column("warehouses", "warehouse_type"); op.drop_column("warehouses", "vendor_id")
