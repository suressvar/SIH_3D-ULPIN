"use client";
import { useEffect, useRef, useState } from "react";
import type { Viewer, Model, Cartesian2, Cesium3DTileset } from "cesium";
import Script from "next/script";
import type { Scene, IssueDetail } from "@/lib/types";
import { useWorkspace } from "@/lib/store";
import { getToken } from "@/lib/api";
import {
  floorFor,
  floorOffset,
  visible,
  appearanceActive,
} from "@/lib/view-math";
declare global {
  interface Window {
    CESIUM_BASE_URL: string;
    Cesium?: typeof import("cesium");
  }
}
export default function Map3D(props: { scene: Scene; conflict?: IssueDetail }) {
  const [loaded, setLoaded] = useState(false),
    [failed, setFailed] = useState(false);
  return (
    <>
      <Script
        src="/cesium/Cesium.js"
        strategy="afterInteractive"
        onReady={() => setLoaded(true)}
        onError={() => {
          setFailed(true);
          useWorkspace.getState().set({
            mode: "2D",
            notice: "3D engine unavailable. Showing the 2D cadastral view.",
          });
        }}
      />
      {loaded && window.Cesium ? (
        <CesiumScene {...props} C={window.Cesium} />
      ) : (
        <div className="viewer-message">
          {failed
            ? "3D engine could not load. Select the 2D map."
            : "Loading 3D engine…"}
        </div>
      )}
    </>
  );
}
function CesiumScene({
  C,
  scene,
  conflict,
}: {
  scene: Scene;
  conflict?: IssueDetail;
  C: typeof import("cesium");
}) {
  const host = useRef<HTMLDivElement>(null),
    viewer = useRef<Viewer | null>(null),
    models = useRef(new Map<string, Model>()),
    tiles = useRef<Cesium3DTileset | null>(null);
  const [loadedTiles, setLoadedTiles] = useState(0);
  const [ready, setReady] = useState(0),
    [error, setError] = useState("");
  const state = useWorkspace();
  const low = state.performance === "Low-end";
  const exterior = appearanceActive(scene, state);
  const stream =
    !exterior &&
    !!scene.asset?.files["tileset.json"] &&
    !state.exploded &&
    !state.slice &&
    !state.floor &&
    !low &&
    scene.objects
      .filter((o) => scene.asset!.files[o.id + ".glb"])
      .every(
        (o) =>
          scene.asset!.snapshot[o.id] ===
          scene.geometries.find((g) => g.object_id === o.id)?.id,
      );

  useEffect(() => {
    if (!host.current) return;
    window.CESIUM_BASE_URL = "/cesium/";
    let v: Viewer;
    try {
      v = new C.Viewer(host.current, {
        animation: false,
        timeline: false,
        baseLayer: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        selectionIndicator: false,
        infoBox: false,
        skyBox: false,
        skyAtmosphere: false,
        requestRenderMode: true,
        contextOptions: { webgl: { alpha: false } },
      });
    } catch {
      setError("3D graphics unavailable. Use the 2D map.");
      useWorkspace.getState().set({
        mode: "2D",
        notice: "3D graphics unavailable. Showing the 2D cadastral view.",
      });
      return;
    }
    const onContextLost = (event: Event) => {
      event.preventDefault();
      useWorkspace.getState().set({
        mode: "2D",
        notice: "3D graphics context lost. Showing the 2D cadastral view.",
      });
    };
    v.scene.canvas.addEventListener("webglcontextlost", onContextLost);
    viewer.current = v;
    v.scene.backgroundColor = C.Color.fromCssColorString("#f1f2f3");
    v.scene.globe.baseColor = C.Color.fromCssColorString("#e5e9df");
    v.scene.globe.show = false;
    v.scene.screenSpaceCameraController.enableCollisionDetection = false;
    v.scene.postProcessStages.fxaa.enabled = !low;
    // Software WebGL produces unstable shadow depth here; retain clean PBR lighting.
    const gl = v.scene.canvas.getContext("webgl2");
    const debugRenderer = gl?.getExtension("WEBGL_debug_renderer_info");
    const softwareGraphics =
      debugRenderer && gl
        ? /swiftshader|llvmpipe|software/i.test(
            String(gl.getParameter(debugRenderer.UNMASKED_RENDERER_WEBGL)),
          )
        : false;
    v.shadows = exterior && !softwareGraphics;
    v.shadowMap.softShadows = true;
    v.shadowMap.size = 2048;
    v.shadowMap.maximumDistance = 200;
    v.shadowMap.darkness = 0.7;
    v.resolutionScale = low ? 0.65 : 1;
    const modelMap = models.current;
    let disposed = false;
    const asset = scene.asset;
    const anchor = asset?.placement || {
      anchor_lon: scene.geometries[0]?.footprint.coordinates[0][0][0] || 0,
      anchor_lat: scene.geometries[0]?.footprint.coordinates[0][0][1] || 0,
    };
    const frame = C.Transforms.eastNorthUpToFixedFrame(
      C.Cartesian3.fromDegrees(anchor.anchor_lon, anchor.anchor_lat, 0),
    );
    if (exterior) {
      v.scene.light = new C.DirectionalLight({
        direction: C.Cartesian3.normalize(
          C.Matrix4.multiplyByPointAsVector(
            frame,
            new C.Cartesian3(-0.5, 0.35, -1),
            new C.Cartesian3(),
          ),
          new C.Cartesian3(),
        ),
        intensity: 1.2,
      });
    }
    const firstFloor = scene.objects
      .filter((o) => o.kind === "FLOOR")
      .sort((a, b) => (a.floor_number ?? 0) - (b.floor_number ?? 0))[0]?.id;
    const available = scene.objects.filter(
      (o) =>
        asset?.files[o.id + ".glb"] &&
        asset.snapshot[o.id] ===
          scene.geometries.find((g) => g.object_id === o.id)?.id &&
        (!low || !floorFor(o, scene) || floorFor(o, scene) === firstFloor),
    );
    const fallback = () => {
      if (!disposed)
        useWorkspace.getState().set({
          mode: "2D",
          notice: "3D asset unavailable. Showing the 2D cadastral view.",
        });
    };
    const watchdog = window.setTimeout(fallback, 30000);
    async function load() {
      if (exterior) {
        try {
          const lighting = new C.ImageBasedLighting();
          lighting.sphericalHarmonicCoefficients = Array.from(
            { length: 9 },
            (_, i) =>
              new C.Cartesian3(
                i === 0 ? 0.7 : 0,
                i === 0 ? 0.72 : 0,
                i === 0 ? 0.75 : 0,
              ),
          );
          const model = await C.Model.fromGltfAsync({
            url: new C.Resource({
              url: asset!.files["appearance.glb"],
              headers: { Authorization: "Bearer " + getToken() },
            }),
            modelMatrix: C.Matrix4.clone(frame),
            id: scene.objects.find((o) => o.kind === "BUILDING")?.id,
            allowPicking: true,
            incrementallyLoadTextures: true,
            imageBasedLighting: lighting,
          });
          if (disposed) {
            model.destroy();
            return;
          }
          modelMap.set("__appearance__", model);
          v.scene.primitives.add(model);
          setReady((n) => n + 1);
          window.clearTimeout(watchdog);
          v.scene.requestRender();
        } catch {
          fallback();
        }
        return;
      }
      if (stream) {
        try {
          const set = await C.Cesium3DTileset.fromUrl(
            new C.Resource({
              url: asset!.files["tileset.json"],
              headers: { Authorization: "Bearer " + getToken() },
            }),
            {
              cacheBytes: 64 * 1024 * 1024,
              maximumCacheOverflowBytes: 16 * 1024 * 1024,
              maximumScreenSpaceError: 24,
              preloadWhenHidden: false,
              preloadFlightDestinations: false,
              showCreditsOnScreen: true,
            },
          );
          if (disposed) {
            set.destroy();
            return;
          }
          tiles.current = set;
          let tileCount = 0;
          set.tileLoad.addEventListener(() => {
            if (!disposed) {
              tileCount++;
              setLoadedTiles(tileCount);
              window.clearTimeout(watchdog);
            }
          });
          set.tileUnload.addEventListener(() => {
            if (!disposed) {
              tileCount = Math.max(0, tileCount - 1);
              setLoadedTiles(tileCount);
            }
          });
          set.tileFailed.addEventListener(fallback);
          v.scene.primitives.add(set);
          v.scene.requestRender();
        } catch {
          fallback();
        }
        return;
      }

      for (const o of available) {
        if (disposed) break;
        try {
          const model = await C.Model.fromGltfAsync({
            url: new C.Resource({
              url: asset!.files[o.id + ".glb"],
              headers: { Authorization: "Bearer " + getToken() },
            }),
            modelMatrix: C.Matrix4.clone(frame),
            id: o.id,
            allowPicking: true,
            incrementallyLoadTextures: true,
            minimumPixelSize: 0,
          });
          if (disposed) {
            model.destroy();
            continue;
          }
          model.clippingPlanes = new C.ClippingPlaneCollection({
            planes: [new C.ClippingPlane(new C.Cartesian3(1, 0, 0), 0)],
            enabled: false,
            edgeWidth: 1,
            edgeColor: C.Color.WHITE,
          });
          modelMap.set(o.id, model);
          v.scene.primitives.add(model);
          setReady((n) => n + 1);
        } catch {
          fallback();
          break;
        }
      }
      window.clearTimeout(watchdog);
    }
    for (const g of exterior ? [] : scene.geometries) {
      const o = scene.objects.find((o) => o.id === g.object_id)!;
      const isModel = available.some((a) => a.id === o.id);
      const coords = g.footprint.coordinates[0].flatMap((p) => [p[0], p[1]]);
      const holes = g.footprint.coordinates
        .slice(1)
        .map(
          (r) =>
            new C.PolygonHierarchy(
              C.Cartesian3.fromDegreesArray(r.flatMap((p) => [p[0], p[1]])),
            ),
        );
      const offset =
        g.elevation_reference === "EPSG:4979"
          ? 0
          : asset?.placement.vertical_offset_to_ellipsoid;
      const zKnown =
        g.elevation_reference === "EPSG:4979" ||
        (offset !== null && offset !== undefined);
      const z = zKnown && g.z_min !== null ? g.z_min + (offset || 0) : 0;
      if (!isModel)
        v.entities.add({
          id: o.id,
          name: o.label,
          polygon: {
            hierarchy: new C.PolygonHierarchy(
              C.Cartesian3.fromDegreesArray(coords),
              holes,
            ),
            height: z,
            extrudedHeight:
              zKnown && g.z_max !== null ? g.z_max + (offset || 0) : undefined,
            material: C.Color.fromCssColorString(
              o.kind === "PARCEL" ? "#dbe2d5" : "#81a99e",
            ).withAlpha(o.kind === "UNIT" ? 0.7 : 0.09),
            outline: true,
            outlineColor: C.Color.fromCssColorString("#779384"),
          },
          properties: { objectId: o.id },
        });
      if (o.kind === "FLOOR") {
        const p = g.footprint.coordinates[0][0];
        v.entities.add({
          id: "label:" + o.id,
          position: C.Cartesian3.fromDegrees(p[0], p[1], z),
          label: {
            text: o.label.replace("Demo / Synthetic Dataset — ", ""),
            font: "12px sans-serif",
            fillColor: C.Color.fromCssColorString("#213a32"),
            showBackground: true,
            backgroundColor: C.Color.WHITE.withAlpha(0.9),
            pixelOffset: new C.Cartesian2(-35, 0),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            show: false,
          },
        });
      }
    }
    const pick = new C.ScreenSpaceEventHandler(v.scene.canvas);
    pick.setInputAction((event: { position: Cartesian2 }) => {
      const hits = v.scene.drillPick(event.position, 12);
      const ids = hits
        .map((p) =>
          typeof p?.id === "string"
            ? p.id
            : p?.id?.id ||
              (p?.content
                ? C.Cesium3DTileFeature.getPropertyInherited(
                    p.content,
                    0,
                    "objectId",
                  )
                : undefined),
        )
        .filter((id) => scene.objects.some((o) => o.id === id));
      const id =
        ids.find(
          (id) => scene.objects.find((o) => o.id === id)?.kind === "UNIT",
        ) || ids[0];
      if (id) useWorkspace.getState().set({ selected: id, issue: null });
    }, C.ScreenSpaceEventType.LEFT_CLICK);
    const center = C.Cartesian3.fromDegrees(
      anchor.anchor_lon,
      anchor.anchor_lat,
      12,
    );
    v.camera.lookAt(
      center,
      new C.HeadingPitchRange(C.Math.toRadians(28), C.Math.toRadians(-32), 100),
    );
    v.camera.lookAtTransform(C.Matrix4.IDENTITY);
    void load();
    setReady((n) => n + 1);
    return () => {
      disposed = true;
      v.scene.canvas.removeEventListener("webglcontextlost", onContextLost);
      pick.destroy();
      window.clearTimeout(watchdog);
      tiles.current = null;
      setLoadedTiles(0);
      modelMap.clear();
      v.destroy();
      viewer.current = null;
    };
  }, [C, scene, low, stream, exterior]);
  useEffect(() => {
    const v = viewer.current;
    if (!v || v.isDestroyed()) return;
    const asset = scene.asset;
    const placement = asset?.placement;
    if (tiles.current) {
      tiles.current.style = new C.Cesium3DTileStyle({
        color: {
          conditions: [
            ["${objectId} === '" + state.selected + "'", "color('#18a58a')"],
            ["true", "color('white')"],
          ],
        },
      });
    }

    for (const o of scene.objects) {
      const model = models.current.get(o.id);
      const show = visible(o, scene, state.floor, low);
      if (model && placement) {
        model.show = show;
        const dz = floorOffset(o, scene, state.exploded);
        model.modelMatrix = C.Transforms.eastNorthUpToFixedFrame(
          C.Cartesian3.fromDegrees(
            placement.anchor_lon,
            placement.anchor_lat,
            dz,
          ),
        );
        model.color =
          o.id === state.selected
            ? C.Color.fromCssColorString("#18a58a")
            : C.Color.WHITE;
        model.colorBlendMode = C.ColorBlendMode.MIX;
        model.colorBlendAmount = o.id === state.selected ? 0.6 : 0;
        model.clippingPlanes.enabled = state.slice;
        model.clippingPlanes.get(0).distance = state.slicePosition;
      }
      const entity = v.entities.getById(o.id);
      if (entity) {
        entity.show = show;
        const g = scene.geometries.find((g) => g.object_id === o.id);
        if (entity.polygon && g) {
          const dz = floorOffset(o, scene, state.exploded);
          const offset =
            g.elevation_reference === "EPSG:4979"
              ? 0
              : placement?.vertical_offset_to_ellipsoid;
          if (offset !== null && offset !== undefined) {
            entity.polygon.height = new C.ConstantProperty(
              (g.z_min || 0) + offset + dz,
            );
            if (g.z_max !== null)
              entity.polygon.extrudedHeight = new C.ConstantProperty(
                g.z_max + offset + dz,
              );
          }
          entity.polygon.outlineColor = new C.ConstantProperty(
            o.id === state.selected
              ? C.Color.fromCssColorString("#00775e")
              : C.Color.fromCssColorString("#779384"),
          );
          if (state.slice && ["BUILDING", "FLOOR"].includes(o.kind))
            entity.show = false;
        }
      }
      const label = v.entities.getById("label:" + o.id);
      if (label) {
        label.show = show && state.exploded && !low;
        const g = scene.geometries.find((g) => g.object_id === o.id)!;
        const p = g.footprint.coordinates[0][0];
        label.position = new C.ConstantPositionProperty(
          C.Cartesian3.fromDegrees(
            p[0],
            p[1],
            (g.z_min || 0) +
              (g.elevation_reference === "EPSG:4979"
                ? 0
                : placement?.vertical_offset_to_ellipsoid || 0) +
              floorOffset(o, scene, state.exploded),
          ),
        );
      }
    }
    v.scene.requestRender();
  }, [
    C,
    scene,
    state.selected,
    state.floor,
    state.exploded,
    state.slice,
    state.slicePosition,
    low,
    ready,
  ]);
  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    const g =
      scene.geometries.find((g) => g.object_id === state.selected) ||
      scene.geometries[0];
    if (!g) return;
    const framing = exterior
      ? scene.geometries.filter((item) =>
          scene.objects.some(
            (o) => o.id === item.object_id && o.kind === "BUILDING",
          ),
        )
      : state.exploded
        ? scene.geometries.filter((item) => {
            const object = scene.objects.find((o) => o.id === item.object_id);
            return object && visible(object, scene, state.floor, low);
          })
        : [g];
    const points = framing.flatMap((item) => {
      const object = scene.objects.find((o) => o.id === item.object_id)!;
      const offset =
        item.elevation_reference === "EPSG:4979"
          ? 0
          : scene.asset?.placement.vertical_offset_to_ellipsoid;
      const known = offset !== null && offset !== undefined;
      const dz = floorOffset(object, scene, state.exploded);
      return item.footprint.coordinates[0].flatMap((p) =>
        [item.z_min, item.z_max].map((z) =>
          C.Cartesian3.fromDegrees(
            p[0],
            p[1],
            known && z !== null ? z + offset + dz : 0,
          ),
        ),
      );
    });
    const bounds = C.BoundingSphere.fromPoints(points);
    v.camera.flyToBoundingSphere(bounds, {
      duration: low ? 0 : 0.35,
      offset: new C.HeadingPitchRange(
        state.reset > 0 ? 0 : 0.6,
        exterior ? -0.46 : -0.5,
        Math.max(exterior ? 35 : 45, bounds.radius * (exterior ? 3.45 : 3.2)),
      ),
    });
    v.scene.requestRender();
  }, [
    C,
    state.selected,
    state.reset,
    state.exploded,
    state.floor,
    scene,
    low,
    exterior,
  ]);
  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    v.entities.removeById("conflict");
    const geometry = conflict?.affected_geometry;
    if (
      geometry &&
      (geometry.type === "Polygon" || geometry.type === "MultiPolygon")
    ) {
      const rings =
        geometry.type === "Polygon"
          ? [geometry.coordinates]
          : geometry.coordinates;
      for (const [i, r] of rings.entries()) {
        v.entities.removeById("conflict:" + i);
        v.entities.add({
          id: "conflict:" + i,
          polygon: {
            hierarchy: C.Cartesian3.fromDegreesArray(
              r[0].flatMap((p) => [p[0], p[1]]),
            ),
            height: conflict?.details.z_min || 0,
            extrudedHeight: conflict?.details.z_max,
            material: C.Color.fromCssColorString("#d75c36").withAlpha(0.8),
          },
        });
      }
    }
    v.scene.requestRender();
    return () => {
      if (!v.isDestroyed())
        for (const e of [...v.entities.values])
          if (e.id.startsWith("conflict:")) v.entities.remove(e);
    };
  }, [C, conflict, scene]);
  const priorZoom = useRef(state.zoom);
  useEffect(() => {
    const v = viewer.current;
    const delta = state.zoom - priorZoom.current;
    priorZoom.current = state.zoom;
    if (v && delta) {
      const amount = Math.max(2, v.camera.positionCartographic.height * 0.15);
      if (delta > 0) v.camera.zoomIn(amount);
      else v.camera.zoomOut(amount);
      v.scene.requestRender();
    }
  }, [state.zoom]);
  return (
    <>
      <div
        ref={host}
        className="canvas"
        aria-label="3D cadastral viewer"
        data-loaded-models={stream ? loadedTiles : models.current.size}
        data-renderer={
          exterior
            ? "illustrative-exterior"
            : stream
              ? "3d-tiles"
              : "glb-prisms"
        }
      />
      {error && (
        <div className="viewer-message" role="alert">
          {error}
          <button onClick={() => state.set({ mode: "2D" })}>Open 2D map</button>
        </div>
      )}
    </>
  );
}
