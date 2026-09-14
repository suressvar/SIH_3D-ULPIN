import { describe, it, expect } from "vitest";
import { floorOffset, visible, appearanceActive } from "./view-math";
import type { Scene, SpatialObject } from "./types";
const objects = [
  { id: "p", kind: "PARCEL", parent_id: null, lifecycle: "ACTIVE" },
  { id: "b", kind: "BUILDING", parent_id: "p", lifecycle: "ACTIVE" },
  {
    id: "f0",
    kind: "FLOOR",
    parent_id: "b",
    floor_number: 0,
    lifecycle: "ACTIVE",
  },
  {
    id: "f1",
    kind: "FLOOR",
    parent_id: "b",
    floor_number: 1,
    lifecycle: "ACTIVE",
  },
  { id: "u", kind: "UNIT", parent_id: "f1", lifecycle: "ACTIVE" },
] as SpatialObject[];
const scene = { objects, geometries: [], identities: {}, asset: null } as Scene;
describe("view transforms", () => {
  it("offsets units with their floor without mutating source records", () => {
    const before = JSON.stringify(scene);
    expect(floorOffset(objects[4], scene, true)).toBe(4);
    expect(floorOffset(objects[4], scene, false)).toBe(0);
    expect(JSON.stringify(scene)).toBe(before);
  });
  it("filters floor children and preserves parcel context", () => {
    expect(visible(objects[4], scene, "f0", false)).toBe(false);
    expect(visible(objects[4], scene, "f1", false)).toBe(true);
    expect(visible(objects[0], scene, "f1", true)).toBe(true);
  });
});

it("hides the exterior for changed envelopes, individual rights and conflicts", () => {
  const current = {
    ...scene,
    geometries: objects.map((o) => ({
      id: "geometry-" + o.id,
      object_id: o.id,
    })),
    asset: {
      files: { "appearance.glb": "/api/v1/exports/test/appearance.glb" },
      snapshot: Object.fromEntries(
        objects.map((o) => [o.id, "geometry-" + o.id]),
      ),
    },
  } as unknown as Scene;
  const state = {
    appearance: true,
    floor: null,
    exploded: false,
    slice: false,
    performance: "Standard",
    selected: "b",
    issue: null,
  };
  expect(appearanceActive(current, state)).toBe(true);
  expect(appearanceActive(current, { ...state, selected: "u" })).toBe(false);
  expect(appearanceActive(current, { ...state, issue: "conflict" })).toBe(
    false,
  );
  const changed = {
    ...current,
    geometries: current.geometries.map((g) =>
      g.object_id === "f1" ? { ...g, id: "new-floor-version" } : g,
    ),
  };
  expect(appearanceActive(changed, state)).toBe(false);
});
