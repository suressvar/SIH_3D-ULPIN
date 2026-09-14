"""Versioned explanatory catalog. Thresholds describe the actual implemented prism rules."""

from app.config import get_settings

RULESET_VERSION = "ASTRA-PRISM-3"
VOLUME_EPSILON_M3 = 1e-6
AREA_EPSILON_M2 = 1e-4
FLOAT_EPSILON_M = 1e-6


def rule_catalog():
    # (id, name, operation, severity, threshold, guidance)
    rows = [
        (
            "INVALID_VOLUME",
            "Invalid closed volume",
            "Triangulation, oriented edge incidence, signed volume and PostGIS ST_IsClosed",
            "CRITICAL",
            None,
            "Correct invalid footprint, face winding or vertical bounds.",
        ),
        (
            "EXCLUSIVE_VOLUME_OVERLAP",
            "Exclusive unit overlap",
            "Metric footprint intersection area × shared vertical interval",
            "ERROR",
            {"value": VOLUME_EPSILON_M3, "unit": "m3"},
            "Correct unit boundaries; access rights do not erase exclusive ownership-volume overlap.",
        ),
        (
            "UNIT_COMMON_SPACE_INTERSECTION",
            "Unit and shared space intersection",
            "Prism intersection plus recorded relationships and scoped rights",
            "WARNING",
            {"value": VOLUME_EPSILON_M3, "unit": "m3"},
            "Review geometry classification, scoped access/shared rights, and supporting documents.",
        ),
        (
            "PERMITTED_SHARED_INTERSECTION",
            "Recorded shared association",
            "Prism intersection with explicit relationship or scoped shared/access record",
            "INFO",
            {"value": VOLUME_EPSILON_M3, "unit": "m3"},
            "Inspect the recorded association and its evidence; this is not a title decision.",
        ),
        (
            "FLOATING_VOLUME",
            "Unit above floor base",
            "Unit lower elevation minus parent floor lower elevation",
            "WARNING",
            {"value": FLOAT_EPSILON_M, "unit": "m"},
            "Check elevations or the explicitly recorded air-right classification.",
        ),
        (
            "REGISTERED_VOLUME_PENETRATION",
            "Other-parcel registered penetration",
            "Intersection with current prototype-accepted geometry on another parcel",
            "CRITICAL",
            {"value": VOLUME_EPSILON_M3, "unit": "m3"},
            "Inspect both records and their evidence. No legal conclusion is generated.",
        ),
        (
            "UNINTENDED_GAP",
            "Unmapped complete partition",
            "Floor footprint minus union of children; only when complete partition was requested",
            "WARNING",
            {"value": AREA_EPSILON_M2, "unit": "m2"},
            "Map the missing space or explain walls/voids and remove the complete-partition assertion.",
        ),
        (
            "OUTSIDE_PARENT",
            "Outside immediate parent",
            "Footprint covers test",
            "ERROR",
            None,
            "Correct the boundary or supply the relevant easement/infrastructure context.",
        ),
        (
            "OUTSIDE_PARENT_PARCEL",
            "Outside root parcel",
            "Footprint difference from parent parcel",
            "ERROR",
            {
                "value": 1e-14,
                "unit": "degree2",
                "note": "numerical residual guard; not a survey tolerance",
            },
            "Reconcile the root parcel and property boundary.",
        ),
        (
            "OUTSIDE_PARENT_HEIGHT",
            "Vertical boundary violation",
            "Child interval within parent interval",
            "ERROR",
            None,
            "Correct vertical limits using the same elevation reference.",
        ),
        (
            "INVALID_HIERARCHY",
            "Invalid spatial hierarchy",
            "Parent kind, root linkage and synthetic designation checks",
            "ERROR",
            None,
            "Place the object under the correct spatial parent; database constraints also prevent invalid insertion.",
        ),
        (
            "HEIGHT_REQUIRED",
            "Missing vertical extent",
            "Required explicit lower and upper elevation",
            "ERROR",
            None,
            "Supply height and its source; no default is assumed.",
        ),
        (
            "ESTIMATED_HEIGHT",
            "Height estimated",
            "Recorded height_estimated flag",
            "WARNING",
            None,
            "Inspect the supplied height method and evidence.",
        ),
        (
            "PARENT_GEOMETRY_MISSING",
            "Missing parent geometry",
            "Parent current geometry lookup",
            "ERROR",
            None,
            "Map the parent before validating this object.",
        ),
        (
            "VERTICAL_REFERENCE_MISMATCH",
            "Parent elevation reference mismatch",
            "Exact named reference comparison",
            "ERROR",
            None,
            "Align vertical references using a documented transformation.",
        ),
        (
            "INCOMPARABLE_NEIGHBOUR",
            "Neighbour elevation reference mismatch",
            "Comparison prerequisite for exclusive volumes",
            "ERROR",
            None,
            "Supply compatible elevation references before comparing volumes.",
        ),
        (
            "REGISTERED_REFERENCE_MISMATCH",
            "Registered space reference mismatch",
            "Comparison prerequisite for registered volumes",
            "ERROR",
            None,
            "Align sources before calculating vertical penetration.",
        ),
        (
            "PARTITION_NOT_COMPARABLE",
            "Floor partition not comparable",
            "Child vertical bounds and reference equal floor",
            "ERROR",
            None,
            "Use equal vertical intervals for a complete floor partition.",
        ),
        (
            "SUPERSEDED_OBJECT",
            "Superseded property",
            "Lifecycle lookup",
            "ERROR",
            None,
            "Inspect successor property versions.",
        ),
        (
            "VERTICAL_EXTENT_LIMIT",
            "Processing extent limit",
            "Upper minus lower elevation",
            "CRITICAL",
            {"value": get_settings().max_vertical_extent_m, "unit": "m"},
            "Check source units. This processing limit is not a legal height restriction.",
        ),
    ]
    return {
        key: {
            "rule_id": key,
            "name": name,
            "description": operation,
            "object_types": (
                ["UNIT", "SHARED"]
                if "SHARED" in key or "COMMON" in key
                else [
                    "PARCEL",
                    "BUILDING",
                    "FLOOR",
                    "UNIT",
                    "UNDERGROUND",
                    "SHARED",
                    "EASEMENT",
                    "INFRASTRUCTURE",
                ]
            ),
            "geometry_operation": operation,
            "threshold": threshold,
            "severity": severity,
            "resolution_guidance": guidance,
            "ruleset_version": RULESET_VERSION,
            "context_note": "Easement/infrastructure containment may be WARNING; actual finding carries the evaluated severity.",
        }
        for key, name, operation, severity, threshold, guidance in rows
    }
