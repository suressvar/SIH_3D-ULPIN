"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Scene, IssueDetail } from "@/lib/types";
import { visible } from "@/lib/view-math";
import { useWorkspace } from "@/lib/store";
export default function Map2D({
  scene,
  conflict,
}: {
  scene: Scene;
  conflict?: IssueDetail;
}) {
  const [failed, setFailed] = useState(false);
  const host = useRef<HTMLDivElement>(null),
    map = useRef<maplibregl.Map | null>(null);
  const selected = useWorkspace((s) => s.selected),
    floor = useWorkspace((s) => s.floor),
    reset = useWorkspace((s) => s.reset),
    zoom = useWorkspace((s) => s.zoom);
  useEffect(() => {
    if (!host.current) return;
    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({
        container: host.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#edf0eb" },
            },
          ],
        },
        center: (scene.geometries[0]?.footprint.coordinates[0][0].slice(
          0,
          2,
        ) as [number, number]) || [0, 0],
        zoom: 16,
        attributionControl: { compact: true },
      });
    } catch {
      setFailed(true);
      useWorkspace.getState().set({
        notice:
          "WebGL unavailable. Showing source footprints in a basic 2D view.",
      });
      return;
    }
    map.current = m;
    m.addControl(new maplibregl.NavigationControl());
    m.on("load", () => {
      m.addSource("properties", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: scene.geometries.map((g) => ({
            type: "Feature",
            geometry: g.footprint,
            properties: {
              id: g.object_id,
              kind: scene.objects.find((o) => o.id === g.object_id)?.kind,
            },
          })),
        },
      });
      m.addLayer({
        id: "fill",
        type: "fill",
        source: "properties",
        paint: { "fill-color": "#82b8ad", "fill-opacity": 0.12 },
      });
      m.addLayer({
        id: "line",
        type: "line",
        source: "properties",
        paint: { "line-color": "#547269", "line-width": 1.5 },
      });
      m.addSource("selection", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "selected",
        type: "line",
        source: "selection",
        paint: { "line-color": "#00695c", "line-width": 4 },
      });
      m.addSource("conflict", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "conflicts",
        type: "fill",
        source: "conflict",
        paint: { "fill-color": "#c3482b", "fill-opacity": 0.6 },
      });
      const points = scene.geometries.flatMap(
        (g) => g.footprint.coordinates[0],
      );
      if (points.length) {
        const b = new maplibregl.LngLatBounds();
        points.forEach((p) => b.extend([p[0], p[1]]));
        m.fitBounds(b, { padding: 90, duration: 0 });
      }
    });
    m.on("click", (e) => {
      const features = m.queryRenderedFeatures(e.point, { layers: ["fill"] });
      const hit =
        features.find((f) => f.properties.kind === "UNIT") || features[0];
      if (hit)
        useWorkspace
          .getState()
          .set({ selected: hit.properties.id, issue: null });
    });
    return () => {
      m.remove();
      map.current = null;
    };
  }, [scene]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const update = () => {
      const g = scene.geometries.find((g) => g.object_id === selected);
      (
        m.getSource("selection") as maplibregl.GeoJSONSource | undefined
      )?.setData({
        type: "FeatureCollection",
        features: g
          ? [{ type: "Feature", properties: {}, geometry: g.footprint }]
          : [],
      });
      const ids = floor
        ? scene.objects
            .filter((o) => o.id === floor || o.parent_id === floor)
            .map((o) => o.id)
        : scene.objects.map((o) => o.id);
      m.setFilter("fill", ["in", ["get", "id"], ["literal", ids]]);
      if (g) {
        const b = new maplibregl.LngLatBounds();
        g.footprint.coordinates[0].forEach((p) => b.extend([p[0], p[1]]));
        m.fitBounds(b, { padding: 90, duration: 250 });
      }
      (
        m.getSource("conflict") as maplibregl.GeoJSONSource | undefined
      )?.setData({
        type: "FeatureCollection",
        features: conflict?.affected_geometry
          ? [
              {
                type: "Feature",
                properties: {},
                geometry: conflict.affected_geometry,
              },
            ]
          : [],
      });
    };
    if (m.isStyleLoaded()) update();
    else m.once("load", update);
    return () => {
      m.off("load", update);
    };
  }, [selected, floor, reset, conflict, scene]);
  const priorZoom = useRef(zoom);
  useEffect(() => {
    const delta = zoom - priorZoom.current;
    priorZoom.current = zoom;
    if (map.current && delta)
      map.current.zoomTo(map.current.getZoom() + Math.sign(delta) * 0.5, {
        duration: 150,
      });
  }, [zoom]);
  if (failed) return <StaticMap scene={scene} conflict={conflict} />;
  return <div ref={host} className="canvas" aria-label="2D parcel map" />;
}

function StaticMap({
  scene,
  conflict,
}: {
  scene: Scene;
  conflict?: IssueDetail;
}) {
  const state = useWorkspace(),
    points = scene.geometries.flatMap((g) => g.footprint.coordinates.flat()),
    xs = points.map((p) => p[0]),
    ys = points.map((p) => p[1]);
  if (!points.length)
    return <p className="viewer-message">No source footprint is available.</p>;
  const x = Math.min(...xs),
    y = Math.min(...ys),
    w = Math.max(...xs) - x || 1,
    h = Math.max(...ys) - y || 1;
  function path(rings: number[][][]) {
    return rings
      .map(
        (r) =>
          r
            .map(
              (p, i) =>
                (i ? "L" : "M") +
                (30 + ((p[0] - x) / w) * 640) +
                "," +
                (470 - ((p[1] - y) / h) * 440),
            )
            .join(" ") + "Z",
      )
      .join(" ");
  }
  return (
    <svg
      className="static-map"
      aria-label="Basic 2D source footprint view"
      viewBox={`${350 - 350 / 1.2 ** Math.max(-5, Math.min(8, state.zoom))} ${250 - 250 / 1.2 ** Math.max(-5, Math.min(8, state.zoom))} ${700 / 1.2 ** Math.max(-5, Math.min(8, state.zoom))} ${500 / 1.2 ** Math.max(-5, Math.min(8, state.zoom))}`}
    >
      {scene.geometries
        .filter((g) => {
          const o = scene.objects.find((o) => o.id === g.object_id);
          return o && visible(o, scene, state.floor, false);
        })
        .map((g) => (
          <path
            key={g.id}
            d={path(g.footprint.coordinates)}
            fill={g.object_id === state.selected ? "#0f766e" : "#91b5a8"}
            fillOpacity={g.object_id === state.selected ? 0.6 : 0.16}
            fillRule="evenodd"
            stroke="#416e60"
            strokeWidth={g.object_id === state.selected ? 3 : 1}
            role="button"
            tabIndex={0}
            aria-label={scene.objects.find((o) => o.id === g.object_id)?.label}
            onClick={() => state.set({ selected: g.object_id, issue: null })}
            onKeyDown={(e) => {
              if (e.key === "Enter")
                state.set({ selected: g.object_id, issue: null });
            }}
          />
        ))}
      {conflict?.affected_geometry?.type === "Polygon" && (
        <path
          d={path(conflict.affected_geometry.coordinates)}
          fill="#c3482b"
          fillOpacity={0.7}
          fillRule="evenodd"
        />
      )}
      <text x="30" y="492" fontSize="12" fill="#466052">
        Source footprints · basic 2D fallback · no external basemap
      </text>
    </svg>
  );
}
