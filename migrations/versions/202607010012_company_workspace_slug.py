from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "202607010012"
down_revision = "202607010011"
branch_labels = None
depends_on = None


SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_slug(value: str) -> str:
    slug = SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return slug or "company"


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(length=120), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM companies ORDER BY created_at, id"))
    used_slugs: set[str] = set()
    for row in rows.mappings():
        base_slug = normalize_slug(str(row["name"] or "company"))
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        connection.execute(
            sa.text("UPDATE companies SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row["id"]},
        )

    with op.batch_alter_table("companies") as batch_op:
        batch_op.alter_column("slug", existing_type=sa.String(length=120), nullable=False)
        batch_op.create_unique_constraint("uq_companies_slug", ["slug"])


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_constraint("uq_companies_slug", type_="unique")
        batch_op.drop_column("slug")
