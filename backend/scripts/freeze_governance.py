from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base

names = {"workflow_events", "right_scopes", "property_annotations"}
statements = [
    "ALTER TABLE cadastre.property_rights DROP CONSTRAINT right_type;",
    "ALTER TABLE cadastre.property_rights ADD CONSTRAINT right_type CHECK (right_type IN ('RECORDED_OWNERSHIP','SHARED_USE','ACCESS','EASEMENT','RESTRICTION'));",
]
for table in Base.metadata.sorted_tables:
    if table.name in names:
        statements.append(
            str(CreateTable(table).compile(dialect=postgresql.dialect())) + ";"
        )
        statements.extend(
            str(CreateIndex(i).compile(dialect=postgresql.dialect())) + ";"
            for i in sorted(table.indexes, key=lambda i: i.name)
        )
for name in sorted(names):
    statements.extend(
        [
            f"ALTER TABLE cadastre.{name} ENABLE ROW LEVEL SECURITY;",
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON cadastre.{name} FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();",
        ]
    )
statements.append("""
DO $$ DECLARE t text; BEGIN
IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='astra_app') THEN
 FOREACH t IN ARRAY ARRAY['workflow_events','right_scopes','property_annotations'] LOOP
  EXECUTE format('CREATE POLICY backend_access ON cadastre.%I TO astra_app USING (true) WITH CHECK (true)',t);
  EXECUTE format('GRANT SELECT,INSERT ON cadastre.%I TO astra_app',t);
 END LOOP;
 GRANT USAGE,SELECT ON SEQUENCE cadastre.workflow_events_sequence_seq,cadastre.property_annotations_sequence_seq TO astra_app;
 GRANT UPDATE(role,active) ON cadastre.app_users TO astra_app;
END IF;
END $$;
""")
Path(__file__).parents[1].joinpath(
    "migrations/versions/0005_governance.sql"
).write_text("\n-- ASTRA STATEMENT\n".join(statements), encoding="utf-8")
