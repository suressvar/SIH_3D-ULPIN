import type { Scene, SpatialObject } from "./types";
export function floorFor(object: SpatialObject, scene: Scene) {
  let current: SpatialObject | undefined = object;
  for (let i = 0; i < 6 && current; i++) {
    if (current.kind === "FLOOR") return current.id;
    current = scene.objects.find((o) => o.id === current?.parent_id);
  }
  return null;
}
export function floorOffset(
  object: SpatialObject,
  scene: Scene,
  exploded: boolean,
) {
  if (!exploded) return 0;
  const floor = floorFor(object, scene);
  const levels = scene.objects
    .filter((o) => o.kind === "FLOOR")
    .sort((a, b) => (a.floor_number ?? 0) - (b.floor_number ?? 0));
  return floor
    ? Math.max(
        0,
        levels.findIndex((f) => f.id === floor),
      ) * 4
    : 0;
}
export function visible(
  object: SpatialObject,
  scene: Scene,
  floor: string | null,
  low: boolean,
) {
  if (object.lifecycle !== "ACTIVE") return false;
  if (floor && object.kind !== "PARCEL")
    return object.id === floor || floorFor(object, scene) === floor;
  return !(low && ["BUILDING", "FLOOR"].includes(object.kind));
}

/** An illustration must never obscure a selected right, conflict or changed envelope. */
export function appearanceActive(
  scene: Scene,
  state: {
    appearance: boolean;
    floor: string | null;
    exploded: boolean;
    slice: boolean;
    performance: string;
    selected: string | null;
    issue: string | null;
  },
) {
  return Boolean(
    state.appearance &&
    scene.asset?.files["appearance.glb"] &&
    !state.floor &&
    !state.exploded &&
    !state.slice &&
    !state.issue &&
    state.performance !== "Low-end" &&
    ["PARCEL", "BUILDING"].includes(
      scene.objects.find((o) => o.id === state.selected)?.kind || "PARCEL",
    ) &&
    scene.objects
      .filter((o) => ["BUILDING", "FLOOR", "PARCEL"].includes(o.kind))
      .every(
        (o) =>
          scene.asset!.snapshot[o.id] ===
          scene.geometries.find((g) => g.object_id === o.id)?.id,
      ),
  );
}
