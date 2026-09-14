from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.models import Source
from app.schemas import Contract, GeometryCreate


class ProcessingRequest(Contract):
    kind: Literal[
        "SUGGEST_BUILDINGS",
        "SUGGEST_UNITS",
        "ESTIMATE_HEIGHT",
        "SUGGEST_LEVELS",
        "EXPORT_ASSETS",
    ]
    object_id: UUID
    dataset_id: UUID | None = None
    secondary_dataset_id: UUID | None = None
    mode: Literal["MODEL", "BINARY_MASK", "ENCLOSED_ROOMS", "POINT_PLANES"] = "MODEL"
    threshold: float = Field(default=0.5, gt=0, lt=1)
    min_area_m2: float = Field(default=1, gt=0)
    vertical_reference: str | None = Field(default=None, min_length=1, max_length=160)
    pixel_to_source: list[float] | None = Field(
        default=None, min_length=6, max_length=6
    )
    source_crs: str | None = None
    vertical_offset_to_ellipsoid: float | None = None

    @model_validator(mode="after")
    def required_inputs(self):
        if self.kind != "EXPORT_ASSETS" and self.dataset_id is None:
            raise ValueError("This processing operation requires a source dataset")
        if self.kind == "ESTIMATE_HEIGHT" and (
            self.secondary_dataset_id is None or not self.vertical_reference
        ):
            raise ValueError(
                "Height estimation requires DSM, DEM and explicit common vertical reference"
            )
        return self


class SuggestionAdopt(Contract):
    target_kind: Literal["UNIT", "SHARED"] | None = None
    decision: Literal["ADOPTED_AS_DRAFT", "REJECTED"]
    reason: str = Field(min_length=5, max_length=3000)
    geometry: GeometryCreate | None = None
    semantic_type: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def require_geometry(self):
        if self.decision == "ADOPTED_AS_DRAFT" and self.geometry is None:
            raise ValueError("Adoption requires explicit, human-confirmed geometry")
        return self


class HeightInput(Contract):
    object_id: UUID
    dataset_id: UUID
    height_value: float = Field(gt=0, le=1000)
    base_elevation: float
    height_source: Literal["SURVEY", "APPROVED_PLAN", "MANUAL"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    vertical_reference: str = Field(min_length=1, max_length=160)
    estimated: bool = False
    reason: str = Field(min_length=5, max_length=2000)


class Level(Contract):
    label: str = Field(min_length=1, max_length=100)
    number: int
    elevation: float
    upper_elevation: float
    semantic_type: Literal["BASEMENT", "GROUND", "UPPER", "MECHANICAL", "ROOF"]

    @model_validator(mode="after")
    def bounds(self):
        if self.upper_elevation <= self.elevation:
            raise ValueError(
                "A floor volume requires an upper elevation above its lower elevation"
            )
        return self


class FloorLevelsInput(Contract):
    building_id: UUID
    dataset_id: UUID
    levels: list[Level] = Field(min_length=1, max_length=200)
    vertical_reference: str = Field(min_length=1, max_length=160)
    source_category: Source
    reason: str = Field(min_length=5, max_length=2000)

    @model_validator(mode="after")
    def unique_levels(self):
        if len({x.number for x in self.levels}) != len(self.levels):
            raise ValueError("Floor numbers must be unique within this request")
        ordered = sorted(self.levels, key=lambda x: x.elevation)
        if any(
            a.upper_elevation > b.elevation
            for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("Floor volume elevations overlap")
        return self


class ReplacementUnit(Contract):
    label: str = Field(min_length=1, max_length=160)
    geometry: GeometryCreate


class ChangeInput(Contract):
    operation: Literal["REPLACE", "SPLIT", "MERGE"]
    object_ids: list[UUID] = Field(min_length=1, max_length=50)
    expected_geometry_ids: list[UUID] = Field(min_length=1, max_length=50)
    replacements: list[ReplacementUnit] = Field(min_length=1, max_length=50)
    evidence_id: UUID
    review_decision_id: UUID | None = None
    reason: str = Field(min_length=5, max_length=3000)

    @model_validator(mode="after")
    def cardinality(self):
        if len(set(self.object_ids)) != len(self.object_ids) or len(
            self.object_ids
        ) != len(self.expected_geometry_ids):
            raise ValueError(
                "Provide distinct objects and one expected geometry ID per object"
            )
        if self.operation == "REPLACE" and (
            len(self.object_ids) != 1 or len(self.replacements) != 1
        ):
            raise ValueError("Replacement requires one input and one output")
        if self.operation == "SPLIT" and (
            len(self.object_ids) != 1 or len(self.replacements) < 2
        ):
            raise ValueError("Split requires one input and multiple outputs")
        if self.operation == "MERGE" and (
            len(self.object_ids) < 2 or len(self.replacements) != 1
        ):
            raise ValueError("Merge requires multiple inputs and one output")
        return self


class RelationshipInput(Contract):
    source_id: UUID
    target_id: UUID
    relation: Literal["AFFECTS", "SERVES", "SHARED_BY"]
    evidence_id: UUID
    reason: str = Field(min_length=5, max_length=2000)


class IssueAcknowledge(Contract):
    reason: str = Field(min_length=5, max_length=2000)


class AttestationInput(Contract):
    evidence_id: UUID
    status: Literal["SURVEY_VERIFIED", "PLAN_VERIFIED"]
    reason: str = Field(min_length=5, max_length=2000)
