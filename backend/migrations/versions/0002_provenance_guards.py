"""Protect original source provenance and reject non-finite vertical bounds."""

from alembic import op

revision = "0002_provenance_guards"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION cadastre.protect_original_source() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.object_key <> OLD.object_key OR NEW.sha256 <> OLD.sha256 OR
         NEW.byte_size <> OLD.byte_size OR NEW.source_category <> OLD.source_category OR
         NEW.is_synthetic <> OLD.is_synthetic OR NEW.created_by <> OLD.created_by OR
         NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'Original source provenance is immutable; register a new dataset';
      END IF;
      RETURN NEW;
    END $$;
    """)
    op.execute("""
    CREATE TRIGGER original_source_immutable BEFORE UPDATE ON cadastre.source_datasets
    FOR EACH ROW EXECUTE FUNCTION cadastre.protect_original_source();
    """)
    op.execute("""
    ALTER TABLE cadastre.geometry_versions ADD CONSTRAINT finite_vertical_bounds CHECK (
      (z_min IS NULL OR z_min NOT IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8)) AND
      (z_max IS NULL OR z_max NOT IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8))
    );
    """)
    op.execute("REVOKE ALL ON FUNCTION cadastre.protect_original_source() FROM PUBLIC;")


def downgrade():
    raise RuntimeError(
        "Do not remove provenance protections without a reviewed migration."
    )
