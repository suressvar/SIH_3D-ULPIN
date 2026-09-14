"""Real PostGIS tests. Never fall back to SQLite or mocked spatial operators."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.main import app, rate_limit
from app.models import (
    AppUser,
    AuditEvent,
    ProcessingJob,
    SourceDataset,
    SpatialObject,
    ValidationIssue,
)
from app.schemas import DecisionCreate, GeometryCreate, ReviewCreate
from app.seed import footprint, seed, uid
from app.services.objects import create_geometry
from app.services.records import decide_review, submit_review
from app.services.validation import require_validation
from app.worker import run_job

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL missing: real PostGIS integration tests not run")
    if not url.rstrip("/").endswith("/astra_test"):
        pytest.fail("Tests require a dedicated database named astra_test")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    if previous is None:
        del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def database(engine, monkeypatch, tmp_path):
    import app.seed as seed_module
    import app.storage as storage
    import app.worker as worker
    from app.config import Settings

    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(seed_module, "get_session", factory)
    monkeypatch.setattr(worker, "get_session", factory)
    monkeypatch.setattr(
        storage, "get_settings", lambda: Settings(storage_root=tmp_path)
    )
    seed()
    with factory() as db:
        yield db
    transaction.rollback()
    connection.close()


def test_seed_generates_real_shells_overlap_issues_and_history(database):
    db = database
    assert db.scalar(select(text("count(*)")).select_from(SpatialObject)) == 13
    assert (
        db.scalar(
            text(
                "SELECT count(*) FROM cadastre.geometry_versions WHERE shell IS NOT NULL AND ST_NDims(shell)=3"
            )
        )
        == 12
    )
    assert (
        db.scalar(
            text(
                "SELECT count(*) FROM cadastre.geometry_versions WHERE shell IS NOT NULL AND ST_IsClosed(shell)"
            )
        )
        == 12
    )
    issues = list(
        db.scalars(
            select(ValidationIssue).where(
                ValidationIssue.code == "EXCLUSIVE_VOLUME_OVERLAP"
            )
        )
    )
    assert len(issues) == 2
    assert all(
        i.details["intersection_volume_m3"] == pytest.approx(51, rel=1e-6)
        for i in issues
    )
    assert db.scalar(select(AuditEvent).limit(1))
    assert seed()["status"] == "already seeded"


def test_database_enforces_hierarchy_and_append_only_records(database):
    db = database
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE cadastre.geometry_versions SET method='rewritten'"))
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("DELETE FROM cadastre.audit_events"))
    with pytest.raises(DBAPIError), db.begin_nested():
        db.add(
            SpatialObject(
                kind="UNIT",
                label="wrong parent",
                parent_id=uid("parcel"),
                parcel_id=uid("parcel"),
                is_synthetic=True,
                created_by=uid("surveyor"),
            )
        )
        db.flush()


def test_revision_invalidates_review_validation(database):
    db = database
    job = db.get(ProcessingJob, uid("validation-unit-201"))
    assert require_validation(db, job.geometry_id).id == job.id
    create_geometry(
        db,
        uid("unit-202"),
        GeometryCreate(
            footprint=footprint(12, 3, 20, 20),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=3,
            z_max=6,
            elevation_reference="SYNTHETIC_LOCAL_DATUM",
            source_category="MANUAL",
            method="Synthetic boundary correction",
        ),
        uid("surveyor"),
    )
    with pytest.raises(HTTPException) as exc:
        require_validation(db, job.geometry_id)
    assert exc.value.status_code == 409


def test_officer_review_requires_separate_actor_and_persists_decision(database):
    db = database
    job = db.get(ProcessingJob, uid("validation-unit-201"))
    case = submit_review(
        db,
        ReviewCreate(geometry_id=job.geometry_id, validation_job_id=job.id),
        uid("surveyor"),
    )
    payload = DecisionCreate(
        decision="ACCEPTED_PROTOTYPE",
        reason="Synthetic fixture reviewed; no legal effect",
    )
    with pytest.raises(HTTPException) as exc:
        decide_review(db, case.id, payload, uid("surveyor"))
    assert exc.value.status_code == 403
    result = decide_review(db, case.id, payload, uid("officer"))
    db.flush()
    assert result.decision == "ACCEPTED_PROTOTYPE"
    assert case.status == "ACCEPTED_PROTOTYPE"


def test_api_upload_worker_failure_retains_original_and_does_not_complete(database):
    db = database

    def db_override():
        yield db
        db.flush()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: db.get(AppUser, uid("surveyor"))
    app.dependency_overrides[rate_limit] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/datasets",
                data={
                    "source_category": "MANUAL",
                    "intent": "parcel",
                    "metric_srid": 32644,
                    "is_synthetic": "true",
                },
                files={
                    "file": ("bad.geojson", b"not valid geojson", "application/json")
                },
            )
            assert response.status_code == 201, response.text
            from uuid import UUID

            dataset_id = UUID(response.json()["id"])
            job = db.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.input_dataset_id == dataset_id
                )
            )
            db.commit()
            run_job(str(job.id))
            db.expire_all()
            assert db.get(ProcessingJob, job.id).status == "FAILED"
            assert db.get(SourceDataset, dataset_id).status == "REJECTED"
            assert (
                client.get(f"/api/v1/datasets/{dataset_id}/original").content
                == b"not valid geojson"
            )
            assert (
                client.get(f"/api/v1/processing/{job.id}").json()["status"] == "FAILED"
            )
    finally:
        app.dependency_overrides.clear()


def test_successful_ingestion_is_atomic_and_duplicate_delivery_is_safe(database):
    import json

    from app.services.ingestion import register_dataset

    db = database
    doc = {
        "type": "Feature",
        "properties": {"label": "Demo imported parcel"},
        "geometry": footprint(),
    }
    source = register_dataset(
        db,
        json.dumps(doc).encode(),
        "parcel.geojson",
        "MANUAL",
        uid("surveyor"),
        True,
        "parcel",
        "EPSG:32644",
        32644,
    )
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.input_dataset_id == source.id)
    )
    job_id = str(job.id)
    db.commit()
    run_job(job_id)
    db.expire_all()
    assert db.get(ProcessingJob, job.id).status == "COMPLETED"
    before = len(list(db.scalars(select(SpatialObject))))
    run_job(job_id)
    db.expire_all()
    assert len(list(db.scalars(select(SpatialObject)))) == before


def test_restricted_runtime_role_can_write_geometry_but_not_rewrite_history(database):
    db = database
    db.execute(text("SET LOCAL ROLE astra_app"))
    assert db.scalar(select(SpatialObject).limit(1))
    created = create_geometry(
        db,
        uid("unit-202"),
        GeometryCreate(
            footprint=footprint(12, 3, 20, 20),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=3,
            z_max=6,
            elevation_reference="SYNTHETIC_LOCAL_DATUM",
            source_category="MANUAL",
            method="Restricted runtime role correction",
        ),
        uid("surveyor"),
    )
    assert created.version == 2
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE cadastre.audit_events SET action='tampered'"))
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE cadastre.source_datasets SET sha256=repeat('0',64)"))
    db.execute(text("RESET ROLE"))


def test_api_reads_persisted_volume_and_cancels_a_real_queued_job(database):
    db = database

    def db_override():
        yield db
        db.flush()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: db.get(AppUser, uid("surveyor"))
    app.dependency_overrides[rate_limit] = lambda: None
    try:
        with TestClient(app) as client:
            unit_id = uid("unit-201")
            response = client.get(f"/api/v1/units/{unit_id}")
            assert response.status_code == 200, response.text
            assert response.json()["is_synthetic"] is True
            geometry = client.get(f"/api/v1/3d/{unit_id}").json()
            assert geometry["z_min"] == 3
            assert geometry["elevation_reference"] == "SYNTHETIC_LOCAL_DATUM"
            assert geometry["source_category"] == "MANUAL"
            queued = client.post(
                "/api/v1/processing",
                json={"kind": "VALIDATE_PRISM", "geometry_id": geometry["id"]},
            )
            assert queued.status_code == 202, queued.text
            job_id = queued.json()["id"]
            cancelled = client.post(f"/api/v1/processing/{job_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "CANCELLED"
            assert (
                client.get(f"/api/v1/processing/{job_id}").json()["status"]
                == "CANCELLED"
            )
            assert (
                client.get(f"/api/v1/rights?object_id={unit_id}").json()[0][
                    "is_synthetic"
                ]
                is True
            )
    finally:
        app.dependency_overrides.clear()


def test_phase2_source_pipeline_and_real_blender_export(
    database, monkeypatch, tmp_path
):
    from sqlalchemy import func

    import app.demo_pipeline as demo_module
    from app.pipeline_models import (
        AssetBundle,
        IdentityVersion,
        SpatialSuggestion,
        SuggestionDecision,
    )
    from app.services.exports import export_available

    if not export_available():
        pytest.skip("Configure Blender and Node tooling for real asset export")
    factory = sessionmaker(
        bind=database.get_bind(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(demo_module, "get_session", factory)
    result = demo_module.demo(tmp_path / "export")
    assert result["floor_count"] == 5
    assert result["space_count"] == 16
    assert result["suggested_plane_count"] == 6
    assert result["geometry_checks"]["khronos_errors"] == 0
    assert (tmp_path / "export/scene.glb").stat().st_size > 100
    import json

    tiles = json.loads((tmp_path / "export/tileset.json").read_text())
    assert tiles["geometricError"] > 0 and tiles["root"]["geometricError"] > 0
    assert all(tile["geometricError"] == 0 for tile in tiles["root"]["children"])
    count = database.scalar(select(func.count()).select_from(AssetBundle))
    repeated = demo_module.demo(tmp_path / "repeat")
    assert repeated["asset_bundle_id"] == result["asset_bundle_id"]
    assert database.scalar(select(func.count()).select_from(AssetBundle)) == count
    assert database.scalar(select(func.count()).select_from(SpatialSuggestion)) == 16
    assert database.scalar(select(func.count()).select_from(SuggestionDecision)) == 16
    assert database.scalar(select(func.count()).select_from(IdentityVersion)) >= 16


def test_semantic_shared_intersection_and_gap_explanation(database):
    from app.models import SpatialRelationship
    from app.repositories import latest_geometry
    from app.services.validation import validate_prism

    db = database
    unit = uid("unit-201")
    original = latest_geometry(db, unit)
    create_geometry(
        db,
        unit,
        GeometryCreate(
            footprint=footprint(3, 3, 11, 20),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=3,
            z_max=6,
            elevation_reference=original.elevation_reference,
            source_category="MANUAL",
            method="Synthetic shared overlap test",
        ),
        uid("surveyor"),
    )

    def check(object_id, parameters=None):
        job = ProcessingJob(
            kind="VALIDATE_PRISM",
            geometry_id=latest_geometry(db, object_id).id,
            created_by=uid("surveyor"),
            parameters=parameters or {},
        )
        db.add(job)
        db.flush()
        validate_prism(db, job)
        db.flush()
        return list(
            db.scalars(select(ValidationIssue).where(ValidationIssue.job_id == job.id))
        )

    issues = check(unit)
    overlap = next(i for i in issues if i.code == "UNIT_COMMON_SPACE_INTERSECTION")
    assert overlap.severity == "WARNING" and overlap.affected_geometry is not None
    assert overlap.details["intersection_volume_m3"] > 0
    db.add(
        SpatialRelationship(
            source_id=uid("shared-corridor"), target_id=unit, relation="SHARED_BY"
        )
    )
    db.flush()
    assert any(
        i.code == "PERMITTED_SHARED_INTERSECTION" and i.severity == "INFO"
        for i in check(unit)
    )
    assert not any(i.code == "UNINTENDED_GAP" for i in check(uid("floor-2")))
    assert any(
        i.code == "UNINTENDED_GAP" and i.affected_geometry is not None
        for i in check(uid("floor-2"), {"require_complete_partition": True})
    )


def test_split_merge_retains_history_and_does_not_transfer_rights(database):
    from uuid import UUID

    from app.models import Evidence, PropertyRight
    from app.pipeline_models import ChangeMember
    from app.pipeline_schemas import ChangeInput, ReplacementUnit
    from app.repositories import latest_geometry
    from app.schemas import EvidenceCreate
    from app.services.history import change_property
    from app.services.records import attach_evidence

    db = database
    actor = uid("surveyor")
    unit = uid("unit-201")
    old = latest_geometry(db, unit)
    evidence = db.scalar(select(Evidence).where(Evidence.object_id == unit))

    def replacement(label, bounds):
        return ReplacementUnit(
            label=label,
            geometry=GeometryCreate(
                footprint=footprint(*bounds),
                source_crs="EPSG:32644",
                metric_srid=32644,
                z_min=3,
                z_max=6,
                elevation_reference=old.elevation_reference,
                source_category="MANUAL",
                method="Synthetic area-conserving property change",
            ),
        )

    split = change_property(
        db,
        ChangeInput(
            operation="SPLIT",
            object_ids=[unit],
            expected_geometry_ids=[old.id],
            replacements=[
                replacement("left", (3, 3, 6, 20)),
                replacement("right", (6, 3, 10, 20)),
            ],
            evidence_id=evidence.id,
            reason="Synthetic subdivision test",
        ),
        actor,
    )
    db.flush()
    ids = [UUID(x["object_id"]) for x in split["outputs"]]
    assert db.get(SpatialObject, unit).lifecycle == "SUPERSEDED"
    assert not list(
        db.scalars(select(PropertyRight).where(PropertyRight.object_id.in_(ids)))
    )
    new_evidence = attach_evidence(
        db,
        EvidenceCreate(
            object_id=ids[0],
            dataset_id=evidence.dataset_id,
            description="Synthetic merge evidence",
        ),
        actor,
    )
    merge = change_property(
        db,
        ChangeInput(
            operation="MERGE",
            object_ids=ids,
            expected_geometry_ids=[latest_geometry(db, i).id for i in ids],
            replacements=[replacement("merged", (3, 3, 10, 20))],
            evidence_id=new_evidence.id,
            reason="Synthetic recombination test",
        ),
        actor,
    )
    db.flush()
    assert merge["rights_transferred"] is False
    assert all(db.get(SpatialObject, i).lifecycle == "SUPERSEDED" for i in ids)
    assert len(list(db.scalars(select(ChangeMember)))) == 6


def test_identical_geometry_revision_reuses_code_and_retains_version_link(database):
    from app.models import ULPINIdentity
    from app.pipeline_models import IdentityVersion
    from app.repositories import latest_geometry
    from app.services.history import append_identity_version

    db = database
    unit = uid("unit-201")
    old = latest_geometry(db, unit)
    identity = db.scalar(select(ULPINIdentity).where(ULPINIdentity.object_id == unit))
    previous = append_identity_version(db, identity, old, uid("surveyor"))
    db.flush()
    new = create_geometry(
        db,
        unit,
        GeometryCreate(
            footprint=footprint(3, 3, 10, 20),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=3,
            z_max=6,
            elevation_reference=old.elevation_reference,
            source_category="MANUAL",
            method="Reprocess identical synthetic source",
        ),
        uid("surveyor"),
    )
    repeated = append_identity_version(db, identity, new, uid("surveyor"))
    db.flush()
    assert repeated.canonical_code == previous.canonical_code
    assert repeated.geometry_id != previous.geometry_id
    assert (
        db.scalar(select(IdentityVersion).where(IdentityVersion.geometry_id == new.id))
        is not None
    )


def test_failed_assistance_does_not_reject_original_source(database):
    from app.pipeline_schemas import ProcessingRequest
    from app.services.pipeline import queue_processing

    db = database
    source = db.scalar(
        select(SourceDataset).where(SourceDataset.is_synthetic.is_(True))
    )
    job = queue_processing(
        db,
        ProcessingRequest(
            kind="ESTIMATE_HEIGHT",
            object_id=uid("building"),
            dataset_id=source.id,
            secondary_dataset_id=source.id,
            vertical_reference="SYNTHETIC_LOCAL_DATUM",
        ),
        uid("surveyor"),
    )
    db.commit()
    run_job(str(job.id))
    db.expire_all()
    assert db.get(ProcessingJob, job.id).status == "FAILED"
    assert db.get(SourceDataset, source.id).status == "READY"


def test_cross_parcel_registered_penetration_and_floating_volume(database):
    from app.repositories import latest_geometry
    from app.schemas import ObjectCreate
    from app.services.objects import create_object
    from app.services.validation import validate_prism

    db = database
    actor = uid("surveyor")
    old = latest_geometry(db, uid("unit-201"))
    review = submit_review(
        db,
        ReviewCreate(geometry_id=old.id, validation_job_id=uid("validation-unit-201")),
        actor,
    )
    decide_review(
        db,
        review.id,
        DecisionCreate(
            decision="ACCEPTED_PROTOTYPE", reason="Synthetic overlap test approval"
        ),
        uid("officer"),
    )
    parent = None
    for kind in ["PARCEL", "BUILDING", "FLOOR", "UNIT"]:
        obj = create_object(
            db,
            ObjectCreate(
                kind=kind,
                label="Synthetic cross parcel " + kind,
                parent_id=parent,
                is_synthetic=True,
                floor_number=1 if kind == "FLOOR" else None,
            ),
            actor,
        )
        geom = create_geometry(
            db,
            obj.id,
            GeometryCreate(
                footprint=footprint(3, 3, 10, 20),
                source_crs="EPSG:32644",
                metric_srid=32644,
                z_min=None if kind == "PARCEL" else (4 if kind == "UNIT" else 3),
                z_max=None if kind == "PARCEL" else 6,
                elevation_reference=(
                    None if kind == "PARCEL" else old.elevation_reference
                ),
                source_category="MANUAL",
                method="Synthetic registered-volume penetration test",
            ),
            actor,
        )
        parent = obj.id
    job = ProcessingJob(kind="VALIDATE_PRISM", geometry_id=geom.id, created_by=actor)
    db.add(job)
    db.flush()
    result = validate_prism(db, job)
    db.flush()
    issues = list(
        db.scalars(select(ValidationIssue).where(ValidationIssue.job_id == job.id))
    )
    assert not result["passed"]
    assert any(i.code == "FLOATING_VOLUME" for i in issues)
    assert any(
        i.severity == "CRITICAL" and i.affected_geometry is not None for i in issues
    )


def test_workspace_read_models_use_real_records(database):
    from app.routers.workspace import overview, scene, search

    user = database.get(AppUser, uid("surveyor"))
    result = overview(database, user)["result"]
    assert result["counts"]["UNIT"] == 6
    result = search("unit-201", database, user)["result"]
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == str(uid("unit-201"))
    assert search("not-a-real-property", database, user)["result"]["items"] == []
    result = scene(uid("parcel"), database, user)["result"]
    assert len(result["objects"]) == 13
    unit = next(
        g for g in result["geometries"] if g["object_id"] == str(uid("unit-201"))
    )
    assert unit["area_m2"] == pytest.approx(119, abs=0.01)
    assert unit["volume_m3"] == pytest.approx(357, abs=0.02)


def test_phase4_case_workflow_rules_and_append_only_history(database):
    from app.governance_models import WorkflowEvent
    from app.routers.governance import case, rules

    db = database
    job = db.get(ProcessingJob, uid("validation-unit-201"))
    surveyor = db.get(AppUser, uid("surveyor"))
    officer = db.get(AppUser, uid("officer"))
    review = submit_review(
        db,
        ReviewCreate(geometry_id=job.geometry_id, validation_job_id=job.id),
        surveyor.id,
    )
    decide_review(
        db,
        review.id,
        DecisionCreate(
            decision="ACCEPTED_PROTOTYPE",
            reason="Synthetic evidence reviewed for prototype only",
        ),
        officer.id,
    )
    db.flush()
    result = case(uid("unit-201"), db, officer)["result"]
    assert result["state"] == "ACCEPTED"
    assert result["validation_fresh"] is True
    assert result["evidence"] and result["sources"] and result["ancestors"]
    assert result["decisions"][0]["reviewer_id"] == str(officer.id)
    assert [e["after_state"] for e in result["workflow"]][-2:] == ["REVIEW", "ACCEPTED"]
    assert any(a["action"] == "REVIEW_DECIDED" for a in result["audit"])
    catalog = rules(officer)["result"]
    assert catalog["EXCLUSIVE_VOLUME_OVERLAP"]["threshold"]["value"] == 1e-6
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(
                text(
                    "UPDATE cadastre.workflow_events SET reason='erased' WHERE object_id=:id"
                ),
                {"id": uid("unit-201")},
            )
    assert db.scalar(
        select(WorkflowEvent).where(WorkflowEvent.object_id == uid("unit-201"))
    )


def test_phase4_recorded_right_invalidates_previous_validation(database):
    from app.models import Evidence
    from app.routers.governance import ScopeCreate, add_scope
    from app.schemas import RightCreate
    from app.services.records import record_right

    db = database
    job = db.get(ProcessingJob, uid("validation-unit-201"))
    require_validation(db, job.geometry_id)
    evidence = db.scalar(select(Evidence).where(Evidence.object_id == uid("unit-201")))
    right = record_right(
        db,
        RightCreate(
            object_id=uid("unit-201"),
            evidence_id=evidence.id,
            right_type="ACCESS",
            party_reference="SYNTHETIC party",
            description="Provided access assertion",
            is_synthetic=True,
        ),
        uid("surveyor"),
    )
    with pytest.raises(HTTPException) as failure:
        require_validation(db, job.geometry_id)
    assert failure.value.status_code == 409
    shared = db.scalar(select(SpatialObject).where(SpatialObject.kind == "SHARED"))
    result = add_scope(
        ScopeCreate(
            right_id=right.id,
            related_object_id=shared.id,
            reason="Synthetic explicit shared-space access",
        ),
        db,
        db.get(AppUser, uid("surveyor")),
    )
    assert result["result"]["related_object_id"] == str(shared.id)


def test_phase4_scoped_access_and_restriction_change_shared_conflict(database):
    from app.models import Evidence
    from app.repositories import latest_geometry
    from app.routers.governance import ScopeCreate, add_scope
    from app.schemas import RightCreate
    from app.services.records import record_right
    from app.services.validation import validate_prism

    db = database
    obj = uid("unit-201")
    original = latest_geometry(db, obj)
    geom = create_geometry(
        db,
        obj,
        GeometryCreate(
            footprint=footprint(3, 3, 11, 20),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=3,
            z_max=6,
            elevation_reference=original.elevation_reference,
            source_category="MANUAL",
            method="Synthetic scoped rights test",
        ),
        uid("surveyor"),
    )
    evidence = db.scalar(select(Evidence).where(Evidence.object_id == obj))

    def scope(kind):
        right = record_right(
            db,
            RightCreate(
                object_id=obj,
                evidence_id=evidence.id,
                right_type=kind,
                party_reference="SYNTHETIC",
                description="Provided scope for synthetic test",
                is_synthetic=True,
            ),
            uid("surveyor"),
        )
        add_scope(
            ScopeCreate(
                right_id=right.id,
                related_object_id=uid("shared-corridor"),
                reason="Explicit synthetic corridor scope",
            ),
            db,
            db.get(AppUser, uid("surveyor")),
        )

    def codes():
        job = ProcessingJob(
            kind="VALIDATE_PRISM",
            geometry_id=geom.id,
            created_by=uid("surveyor"),
            parameters={},
        )
        db.add(job)
        db.flush()
        validate_prism(db, job)
        return {
            i.code
            for i in db.scalars(
                select(ValidationIssue).where(ValidationIssue.job_id == job.id)
            )
        }

    assert "UNIT_COMMON_SPACE_INTERSECTION" in codes()
    scope("ACCESS")
    assert "PERMITTED_SHARED_INTERSECTION" in codes()
    scope("RESTRICTION")
    assert "UNIT_COMMON_SPACE_INTERSECTION" in codes()
    assert "PERMITTED_SHARED_INTERSECTION" not in codes()


def test_phase4_metadata_versions_and_last_admin_guard(database):
    from uuid import uuid4

    from app.models import Evidence
    from app.routers.governance import (
        AnnotationCreate,
        MemberUpdate,
        annotate,
        update_member,
    )
    from app.routers.workspace import search

    db = database
    actor = db.get(AppUser, uid("surveyor"))
    evidence = db.scalar(select(Evidence).where(Evidence.object_id == uid("unit-201")))
    payload = AnnotationCreate(
        display_label="Synthetic revised unit",
        address="Demo address supplied for test",
        land_use="Synthetic residential",
        evidence_id=evidence.id,
        reason="Synthetic metadata correction",
    )
    row = annotate(uid("unit-201"), payload, db, actor)["result"]
    assert row["id"]
    assert search("Demo address supplied", db, actor)["result"]["items"][0][
        "id"
    ] == str(uid("unit-201"))
    with pytest.raises(HTTPException) as failure:
        annotate(uid("unit-201"), payload, db, actor)
    assert failure.value.status_code == 409
    administrator = AppUser(id=uuid4(), role="admin", active=True)
    db.add(administrator)
    db.flush()
    with pytest.raises(HTTPException) as failure:
        update_member(
            administrator.id,
            MemberUpdate(role="viewer", active=True, reason="Test last admin guard"),
            db,
            administrator,
        )
    assert failure.value.status_code == 409


def test_bounded_case_history_paginates_real_versions(database):
    from app.repositories import latest_geometry
    from app.routers.governance import case as object_case
    from app.routers.governance import object_history
    from app.services.objects import geometry_out

    db = database
    user = db.get(AppUser, uid("surveyor"))
    object_id = uid("unit-101")
    original = latest_geometry(db, object_id)
    data = geometry_out(original)
    for _ in range(22):
        create_geometry(
            db,
            object_id,
            GeometryCreate(
                footprint=data.footprint,
                source_crs="EPSG:4326",
                metric_srid=32644,
                z_min=data.z_min,
                z_max=data.z_max,
                elevation_reference=data.elevation_reference,
                source_category="MANUAL",
                method="Synthetic pagination regression boundary revision",
            ),
            user.id,
        )
    case = object_case(object_id, db, user)["result"]
    assert len(case["geometry_versions"]) == 20
    assert case["pagination"]["geometry_versions"]["has_more"] is True
    first = object_history(object_id, "geometry_versions", 20, 0, db, user)["result"]
    older = object_history(
        object_id, "geometry_versions", 20, first["next_offset"], db, user
    )["result"]
    assert first["items"][0]["version"] > older["items"][0]["version"]
    assert older["next_offset"] is None
    assert len({g["id"] for g in first["items"] + older["items"]}) == 23


def test_missing_source_and_database_timeout_are_safe_api_errors(database):
    from sqlalchemy.exc import TimeoutError

    db = database

    def db_override():
        yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: db.get(AppUser, uid("surveyor"))
    app.dependency_overrides[rate_limit] = lambda: None
    try:
        source = db.scalar(select(SourceDataset))
        from app.storage import local_path

        # Delete only this disposable test source to exercise missing-file recovery.
        local_path(source.object_key).unlink()
        with TestClient(app) as client:
            response = client.get(f"/api/v1/datasets/{source.id}/original")
            assert response.status_code == 503
            assert "property record remains accessible" in response.json()["detail"]

            def unavailable():
                raise TimeoutError("sensitive connection details")
                yield

            app.dependency_overrides[get_db] = unavailable
            response = client.get("/api/v1/parcels")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
    finally:
        app.dependency_overrides.clear()
