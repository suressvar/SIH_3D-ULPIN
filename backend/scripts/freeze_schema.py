"""Developer baseline generator; do not rerun after this migration is deployed."""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base

dialect = postgresql.dialect()
statements = ["CREATE EXTENSION IF NOT EXISTS postgis;", "CREATE SCHEMA cadastre;"]
for table in Base.metadata.sorted_tables:
    statements.append(str(CreateTable(table).compile(dialect=dialect)) + ";")
    statements.extend(
        str(CreateIndex(index).compile(dialect=dialect)) + ";"
        for index in sorted(table.indexes, key=lambda x: x.name)
    )
statements.extend(
    Path(__file__).with_name("constraints.sql").read_text().split("-- ASTRA STATEMENT")
)
Path(__file__).parents[1].joinpath("migrations/versions/0001_schema.sql").write_text(
    "\n-- ASTRA STATEMENT\n".join(statements), encoding="utf-8"
)
