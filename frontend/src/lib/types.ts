export type SpatialObject = {
  id: string;
  kind: string;
  label: string;
  parent_id: string | null;
  parcel_id: string | null;
  floor_number: number | null;
  existing_ulpin: string | null;
  is_synthetic: boolean;
  lifecycle: string;
  semantic_type: string | null;
};
export type Geometry = {
  id: string;
  object_id: string;
  version: number;
  footprint: GeoJSON.Polygon;
  metric_srid: number;
  source_crs: string;
  z_min: number | null;
  z_max: number | null;
  elevation_reference: string | null;
  source_category: string;
  source_dataset_id: string | null;
  confidence: number | null;
  method: string;
  height_estimated: boolean;
  area_m2: number;
  volume_m3: number | null;
  created_at: string;
};
export type Scene = {
  objects: SpatialObject[];
  geometries: Geometry[];
  identities: Record<string, string>;
  asset: null | {
    id: string;
    placement: {
      anchor_lon: number;
      anchor_lat: number;
      vertical_offset_to_ellipsoid: number | null;
    };
    snapshot: Record<string, unknown>;
    files: Record<string, string>;
  };
};
export type Issue = {
  id: string;
  geometry_id: string;
  related_geometry_id: string | null;
  code: string;
  severity: string;
  message: string;
  status: string;
  object_id: string;
  object_label: string;
  parcel_id: string;
  details: Record<string, unknown>;
};
export type IssueDetail = {
  affected_geometry: GeoJSON.Geometry | null;
  details: {
    z_min?: number;
    z_max?: number;
    vertical_reference?: string;
    [key: string]: unknown;
  };
};
export type RecordData = Record<string, unknown>;
