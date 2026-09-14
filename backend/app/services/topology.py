"""Additional deterministic prism rules; semantics determine whether overlaps are issues."""

from geoalchemy2.shape import to_shape
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform, unary_union
from sqlalchemy import func, select

from app.config import get_settings
from app.governance_models import RightScope
from app.mesh import prism_mesh
from app.models import (
    GeometryVersion,
    Kind,
    PropertyRight,
    ReviewCase,
    SpatialObject,
    SpatialRelationship,
)
from app.repositories import current_geometries, latest_geometry
from app.rules import RULESET_VERSION


def semantic_snapshot(db, root):
    objects = list(
        db.scalars(
            select(SpatialObject).where(
                (SpatialObject.parcel_id == root) | (SpatialObject.id == root)
            )
        )
    )
    ids = [o.id for o in objects]
    relationships = list(
        db.scalars(
            select(SpatialRelationship)
            .where(
                SpatialRelationship.source_id.in_(ids)
                | SpatialRelationship.target_id.in_(ids)
            )
            .order_by(SpatialRelationship.id)
        )
    )
    registered = list(
        db.execute(
            select(ReviewCase.geometry_id, ReviewCase.id)
            .join(SpatialObject, SpatialObject.id == ReviewCase.object_id)
            .where(
                ReviewCase.status == "ACCEPTED_PROTOTYPE",
                SpatialObject.parcel_id != root,
            )
            .order_by(ReviewCase.id)
        )
    )
    rights = list(
        db.scalars(
            select(PropertyRight)
            .where(
                (PropertyRight.object_id.in_(ids))
                | PropertyRight.id.in_(
                    select(RightScope.right_id).where(
                        RightScope.related_object_id.in_(ids)
                    )
                )
            )
            .order_by(PropertyRight.id)
        )
    )
    scopes = list(
        db.scalars(
            select(RightScope)
            .where(RightScope.right_id.in_([r.id for r in rights]))
            .order_by(RightScope.id)
        )
    )
    return {
        "ruleset_version": RULESET_VERSION,
        "rights": [[str(r.id), r.right_type, str(r.evidence_id)] for r in rights],
        "scopes": [[str(r.right_id), str(r.related_object_id)] for r in scopes],
        "objects": {str(o.id): [o.lifecycle, o.semantic_type] for o in objects},
        "relations": [
            [str(r.source_id), str(r.target_id), r.relation] for r in relationships
        ],
        "registered": [[str(g), str(r)] for g, r in registered],
    }


def extra_rules(db, job, obj, geom, emit):
    footprint = to_shape(geom.footprint)
    metric = to_shape(geom.metric_footprint)
    root = obj.parcel_id or obj.id
    parent_parcel = latest_geometry(db, root)
    metric_to_geo = Transformer.from_crs(geom.metric_srid, 4326, always_xy=True)

    def affected(poly):
        return mapping(transform(metric_to_geo.transform, poly))

    from app.services.objects import PARENTS

    parent_object = db.get(SpatialObject, obj.parent_id) if obj.parent_id else None
    hierarchy_valid = (
        obj.kind == Kind.PARCEL and obj.parent_id is None and obj.parcel_id is None
    ) or (
        parent_object is not None
        and parent_object.kind in PARENTS.get(obj.kind, set())
        and obj.parcel_id
        == (
            parent_object.id
            if parent_object.kind == Kind.PARCEL
            else parent_object.parcel_id
        )
        and obj.is_synthetic == parent_object.is_synthetic
    )
    if not hierarchy_valid:
        emit(
            "INVALID_HIERARCHY",
            "ERROR",
            "Parent kind, root parcel or source designation does not match the spatial hierarchy",
        )
    if obj.lifecycle != "ACTIVE":
        emit(
            "SUPERSEDED_OBJECT",
            "ERROR",
            "This object was replaced by a recorded property change",
        )
    if geom.z_min is not None:
        if geom.z_max - geom.z_min > get_settings().max_vertical_extent_m:
            emit(
                "VERTICAL_EXTENT_LIMIT",
                "CRITICAL",
                "Vertical extent exceeds the configured processing limit; check units and source",
            )
        try:
            prism_mesh(metric, geom.z_min, geom.z_max)
            if not db.scalar(
                select(func.ST_IsClosed(GeometryVersion.shell)).where(
                    GeometryVersion.id == geom.id
                )
            ):
                raise ValueError("PostGIS shell is not closed")
        except ValueError as exc:
            emit("INVALID_VOLUME", "CRITICAL", str(exc))
    if parent_parcel and obj.kind != Kind.PARCEL:
        outside = footprint.difference(to_shape(parent_parcel.footprint))
        if not outside.is_empty and outside.area > 1e-14:
            emit(
                "OUTSIDE_PARENT_PARCEL",
                (
                    "WARNING"
                    if obj.kind in {Kind.EASEMENT, Kind.INFRASTRUCTURE}
                    else "ERROR"
                ),
                f"{obj.label} extends beyond its root parcel; review its evidence",
                parent_parcel,
                {"_affected": mapping(outside)},
            )

    candidates = current_geometries(db, root)
    objects = {g.object_id: db.get(SpatialObject, g.object_id) for g in candidates}
    relations = list(
        db.scalars(
            select(SpatialRelationship).where(
                (SpatialRelationship.source_id == obj.id)
                | (SpatialRelationship.target_id == obj.id)
            )
        )
    )
    permitted = {
        r.target_id if r.source_id == obj.id else r.source_id
        for r in relations
        if r.relation in {"SHARED_BY", "SERVES"}
    }
    restrictions = set()
    for scope, right in db.execute(
        select(RightScope, PropertyRight)
        .join(PropertyRight, PropertyRight.id == RightScope.right_id)
        .where(
            (PropertyRight.object_id == obj.id)
            | (RightScope.related_object_id == obj.id)
        )
    ):
        other_id = (
            scope.related_object_id if right.object_id == obj.id else right.object_id
        )
        if right.right_type in {"SHARED_USE", "ACCESS", "EASEMENT"}:
            permitted.add(other_id)
        elif right.right_type == "RESTRICTION":
            restrictions.add(other_id)
    permitted -= restrictions
    if geom.z_min is not None:
        for other in candidates:
            other_obj = objects[other.object_id]
            if other.id == geom.id or {obj.kind, other_obj.kind} != {
                Kind.UNIT,
                Kind.SHARED,
            }:
                continue
            if (
                other.z_min is None
                or other.elevation_reference != geom.elevation_reference
            ):
                continue
            polygon = transform(
                Transformer.from_crs(4326, geom.metric_srid, always_xy=True).transform,
                to_shape(other.footprint),
            )
            intersection = metric.intersection(polygon)
            low, high = max(geom.z_min, other.z_min), min(geom.z_max, other.z_max)
            if intersection.area * max(high - low, 0) <= 1e-6:
                continue
            allowed = other_obj.id in permitted
            emit(
                (
                    "PERMITTED_SHARED_INTERSECTION"
                    if allowed
                    else "UNIT_COMMON_SPACE_INTERSECTION"
                ),
                "INFO" if allowed else "WARNING",
                f"{obj.label} intersects {other_obj.label}. "
                + (
                    "An explicit shared-use or scoped access association is recorded."
                    if allowed
                    else "No explicit shared-use relationship is recorded; review the boundary or supply evidence."
                ),
                other,
                {
                    "_affected": affected(intersection),
                    "z_min": low,
                    "z_max": high,
                    "vertical_reference": geom.elevation_reference,
                    "intersection_volume_m3": intersection.area * (high - low),
                    "action": "Review boundary or record an evidence-backed shared-use relationship",
                },
            )

    parent = latest_geometry(db, obj.parent_id) if obj.parent_id else None
    if (
        geom.z_min is not None
        and parent
        and parent.z_min is not None
        and geom.elevation_reference == parent.elevation_reference
    ):
        if (
            obj.kind == Kind.UNIT
            and geom.z_min > parent.z_min + 1e-6
            and obj.semantic_type != "AIR_RIGHT"
        ):
            emit(
                "FLOATING_VOLUME",
                "WARNING",
                f"{obj.label} begins above its floor base. Verify vertical bounds; physical support is not inferred",
                parent,
                {
                    "z_min": parent.z_min,
                    "z_max": geom.z_min,
                    "action": "Review floor elevation and source",
                },
            )

    if obj.kind == Kind.FLOOR and job.parameters.get("require_complete_partition"):
        children = [
            g
            for g in candidates
            if objects[g.object_id].parent_id == obj.id
            and objects[g.object_id].kind in {Kind.UNIT, Kind.SHARED}
        ]
        if geom.z_min is None or any(
            g.z_min != geom.z_min
            or g.z_max != geom.z_max
            or g.elevation_reference != geom.elevation_reference
            for g in children
        ):
            emit(
                "PARTITION_NOT_COMPARABLE",
                "ERROR",
                "Complete partition checking requires children with the same floor vertical extent",
            )
        else:
            polygons = [
                transform(
                    Transformer.from_crs(
                        4326, geom.metric_srid, always_xy=True
                    ).transform,
                    to_shape(g.footprint),
                )
                for g in children
            ]
            gap = metric.difference(unary_union(polygons))
            if gap.area > 1e-4:
                emit(
                    "UNINTENDED_GAP",
                    "WARNING",
                    "The explicitly requested complete floor partition leaves unmapped area; walls or voids may explain it",
                    details={
                        "_affected": affected(gap),
                        "area_m2": gap.area,
                        "z_min": geom.z_min,
                        "z_max": geom.z_max,
                        "action": "Map missing space or withdraw the complete-partition assertion",
                    },
                )

    # Registered spatial penetration is distinct from legal ownership determination.
    if geom.z_min is not None and obj.kind in {
        Kind.UNIT,
        Kind.UNDERGROUND,
        Kind.INFRASTRUCTURE,
    }:
        rows = db.scalars(
            select(GeometryVersion)
            .join(ReviewCase, ReviewCase.geometry_id == GeometryVersion.id)
            .join(SpatialObject, SpatialObject.id == GeometryVersion.object_id)
            .where(
                ReviewCase.status == "ACCEPTED_PROTOTYPE",
                SpatialObject.lifecycle == "ACTIVE",
                SpatialObject.parcel_id != root,
                func.ST_Intersects(GeometryVersion.footprint, geom.footprint),
            )
        ).all()
        for other in rows:
            if latest_geometry(db, other.object_id).id != other.id:
                continue
            if (
                other.z_min is None
                or other.elevation_reference != geom.elevation_reference
            ):
                emit(
                    "REGISTERED_REFERENCE_MISMATCH",
                    "ERROR",
                    "An intersecting registered space has incompatible vertical metadata",
                    other,
                )
                continue
            poly = transform(
                Transformer.from_crs(4326, geom.metric_srid, always_xy=True).transform,
                to_shape(other.footprint),
            )
            intersection = metric.intersection(poly)
            low, high = max(geom.z_min, other.z_min), min(geom.z_max, other.z_max)
            if intersection.area * max(high - low, 0) > 1e-6:
                emit(
                    "REGISTERED_VOLUME_PENETRATION",
                    "CRITICAL",
                    "Volume penetrates an unrelated accepted prototype record; review both records",
                    other,
                    {
                        "_affected": affected(intersection),
                        "z_min": low,
                        "z_max": high,
                        "intersection_volume_m3": intersection.area * (high - low),
                    },
                )
