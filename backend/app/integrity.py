"""Read-only relational, provenance and asset integrity audit for a demo database."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import and_, func, select, text

from app import governance_models, pipeline_models  # noqa: F401
from app.db import get_session
from app.models import AuditEvent, Base, SourceDataset, SpatialObject
from app.pipeline_models import AssetBundle
from app.storage import read_bytes


def audit_integrity():
    failures = []
    with get_session() as db:
        tables = {table.name: table for table in Base.metadata.tables.values()}
        counts = {
            name: db.scalar(select(func.count()).select_from(table))
            for name, table in tables.items()
        }
        checked = 0
        for table in tables.values():
            for constraint in table.foreign_key_constraints:
                target = constraint.referred_table.alias()
                terms = [
                    column.parent == target.c[column.column.name]
                    for column in constraint.elements
                ]
                supplied = and_(
                    *(column.parent.is_not(None) for column in constraint.elements)
                )
                missing = db.scalar(
                    select(func.count())
                    .select_from(table.outerjoin(target, and_(*terms)))
                    .where(supplied, next(iter(target.primary_key)).is_(None))
                )
                checked += 1
                if missing:
                    failures.append(
                        {
                            "check": "foreign_key",
                            "table": table.name,
                            "missing": missing,
                        }
                    )
        for (kind,) in db.execute(select(AuditEvent.entity_type).distinct()):
            audit_table = tables.get(kind)
            if audit_table is None:
                failures.append({"check": "unknown_audit_entity", "type": kind})
                continue
            count = db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_type == kind,
                    ~select(audit_table.c.id)
                    .where(audit_table.c.id == AuditEvent.entity_id)
                    .exists(),
                )
            )
            if count:
                failures.append(
                    {"check": "orphan_audit_entity", "type": kind, "count": count}
                )
        objects = {o.id: o for o in db.scalars(select(SpatialObject))}
        for obj in objects.values():
            node, seen = obj, set()
            while node.parent_id is not None:
                if node.id in seen or node.parent_id not in objects:
                    failures.append({"check": "parent_chain", "object_id": str(obj.id)})
                    break
                seen.add(node.id)
                node = objects[node.parent_id]
            else:
                if node.kind != "PARCEL" or (
                    obj.kind != "PARCEL" and obj.parcel_id != node.id
                ):
                    failures.append(
                        {"check": "parcel_traceability", "object_id": str(obj.id)}
                    )
        invalid = db.scalar(
            text(
                "SELECT count(*) FROM cadastre.geometry_versions WHERE NOT ST_IsValid(footprint) OR (shell IS NOT NULL AND NOT ST_IsClosed(shell))"
            )
        )
        if invalid:
            failures.append({"check": "geometry_validity", "count": invalid})
        mismatched_identities = db.scalar(
            text(
                "SELECT count(*) FROM cadastre.identity_versions v JOIN cadastre.geometry_versions g ON g.id=v.geometry_id JOIN cadastre.ulpin_identities i ON i.id=v.identity_id WHERE g.object_id <> i.object_id"
            )
        )
        if mismatched_identities:
            failures.append(
                {"check": "identity_geometry_object", "count": mismatched_identities}
            )
        source_count = 0
        for source in db.scalars(select(SourceDataset)):
            try:
                raw = read_bytes(source.object_key)
                if (
                    len(raw) != source.byte_size
                    or hashlib.sha256(raw).hexdigest() != source.sha256
                ):
                    raise ValueError("Source checksum/size mismatch")
                source_count += 1
            except (OSError, ValueError) as exc:
                failures.append(
                    {
                        "check": "source_file",
                        "dataset_id": str(source.id),
                        "error": type(exc).__name__,
                    }
                )
        asset_count = 0
        for asset in db.scalars(select(AssetBundle)):
            for name, entry in asset.manifest.items():
                try:
                    raw = read_bytes(entry["key"])
                    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                        raise ValueError("Asset checksum mismatch")
                    asset_count += 1
                except (OSError, ValueError, KeyError) as exc:
                    failures.append(
                        {
                            "check": "asset_file",
                            "asset_id": str(asset.id),
                            "name": name,
                            "error": type(exc).__name__,
                        }
                    )
        return {
            "scope": "Read-only database-wide audit; logical conflicts are distinct from orphan/corrupt records",
            "table_counts": counts,
            "foreign_keys_checked": checked,
            "source_files_verified": source_count,
            "asset_files_verified": asset_count,
            "object_kinds": dict(Counter(o.kind for o in objects.values())),
            "failures": failures,
            "passed": not failures,
        }


if __name__ == "__main__":
    report = audit_integrity()
    path = Path("output/final-integrity.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
