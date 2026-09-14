"""Preserve every geometry link even when canonical geometry repeats."""

from alembic import op

revision = "0004_identity_reuse"
down_revision = "0003_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE cadastre.identity_versions DROP CONSTRAINT identity_versions_canonical_code_key"
    )
    op.execute(
        "CREATE INDEX ix_cadastre_identity_versions_canonical_code ON cadastre.identity_versions (canonical_code)"
    )


def downgrade():
    raise RuntimeError(
        "Identity history is retained; use a reviewed forward migration."
    )
