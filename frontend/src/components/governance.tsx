"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download } from "@/lib/api";
import type { Geometry, Scene, SpatialObject } from "@/lib/types";
import type { Member } from "./auth";
import { Button } from "./ui/button";
import { useWorkspace } from "@/lib/store";
import {
  featureCollection,
  feature,
  union,
  intersect,
  bbox,
  bboxPolygon,
} from "@turf/turf";

type Evidence = {
  id: string;
  dataset_id: string;
  description: string;
  created_at: string;
  created_by: string;
};
type Review = {
  id: string;
  geometry_id: string;
  status: string;
  submitted_by: string;
  created_at: string;
};
type Event = {
  id: string;
  before_state: string;
  after_state: string;
  reason: string;
  actor_id: string;
  created_at: string;
};
type Right = {
  id: string;
  right_type: string;
  party_reference: string;
  description: string;
  evidence_id: string;
};
type Case = {
  sources: {
    id: string;
    filename: string;
    source_category: string;
    status: string;
    created_at: string;
  }[];
  attestations: {
    id: string;
    actor_id: string;
    status: string;
    reason: string;
  }[];
  decisions: {
    id: string;
    reviewer_id: string;
    reason: string;
    decision: string;
  }[];
  changes: {
    id: string;
    operation: string;
    reason: string;
    members: { geometry_id: string; direction: string }[];
  }[];
  geometry: Geometry | null;
  state: string;
  validation_fresh: boolean;
  validation_reason: string;
  validation_job: {
    id: string;
    status: string;
    error_message: string | null;
  } | null;
  evidence: Evidence[];
  rights: Right[];
  reviews: Review[];
  workflow: Event[];
  geometry_versions: Geometry[];
  annotations: {
    id: string;
    display_label: string;
    address: string | null;
    land_use: string | null;
  }[];
  issues: {
    id: string;
    code: string;
    severity: string;
    message: string;
    details: Record<string, unknown>;
  }[];
  [key: string]: unknown;
};
function saveJson(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function GovernancePanel({
  obj,
  scene,
  member,
}: {
  obj: SpatialObject;
  scene: Scene;
  member: Member;
}) {
  const client = useQueryClient(),
    store = useWorkspace();
  const [open, setOpen] = useState(false),
    [mode, setMode] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [reason, setReason] = useState(""),
    [evidenceId, setEvidenceId] = useState(""),
    [description, setDescription] = useState(""),
    [party, setParty] = useState(""),
    [rightType, setRightType] = useState("RECORDED_OWNERSHIP"),
    [file, setFile] = useState<File | null>(null),
    [source, setSource] = useState("MANUAL"),
    [footprint, setFootprint] = useState(""),
    [low, setLow] = useState(""),
    [high, setHigh] = useState(""),
    [datum, setDatum] = useState(""),
    [estimated, setEstimated] = useState(false),
    [other, setOther] = useState(""),
    [label, setLabel] = useState(obj.label),
    [address, setAddress] = useState(""),
    [landUse, setLandUse] = useState(""),
    [scopeRight, setScopeRight] = useState("");
  const q = useQuery({
    queryKey: ["case", obj.id],
    queryFn: () => api<{ result: Case }>("/governance/objects/" + obj.id),
    refetchInterval: (query) =>
      open &&
      ["QUEUED", "RUNNING"].includes(
        query.state.data?.result.validation_job?.status || "",
      )
        ? 3000
        : open && query.state.data?.result.state === "REVIEW"
          ? 10000
          : false,
  });
  const d = q.data?.result,
    g = d?.geometry;
  const writer = ["surveyor", "admin"].includes(member.role),
    officer = ["officer", "admin"].includes(member.role);
  async function act(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
      setMode("");
      await client.invalidateQueries();
      setMessage(success);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function begin(next: string) {
    if (busy) return;
    setMode(next);
    setReason("");
    setMessage("");
    setEvidenceId(d?.evidence[0]?.id || "");
    if (g) {
      setFootprint(JSON.stringify(g.footprint, null, 2));
      setLow(g.z_min?.toString() || "");
      setHigh(g.z_max?.toString() || "");
      setDatum(g.elevation_reference || "");
      setEstimated(g.height_estimated);
    }
    const p = d?.annotations.at(-1);
    setLabel(p?.display_label || obj.label);
    setAddress(p?.address || "");
    setLandUse(p?.land_use || "");
  }
  function geometry(poly: GeoJSON.Polygon) {
    if (!g) throw Error("Geometry unavailable");
    return {
      footprint: poly,
      source_crs: "EPSG:4326",
      metric_srid: g.metric_srid,
      z_min: low === "" ? null : Number(low),
      z_max: high === "" ? null : Number(high),
      elevation_reference: datum || null,
      height_estimated: estimated,
      source_category: "MANUAL",
      source_dataset_id:
        d?.evidence.find((e) => e.id === evidenceId)?.dataset_id || null,
      confidence: null,
      method: reason,
    };
  }
  async function change() {
    if (!g) throw Error("Geometry unavailable");
    let polys: GeoJSON.Polygon[] = [JSON.parse(footprint)];
    const inputs = [obj.id],
      expected = [g.id];
    if (mode === "SPLIT") {
      const box = bbox(feature(g.footprint)),
        mid = (box[0] + box[2]) / 2;
      polys = [
        [box[0] - 1, box[1] - 1, mid, box[3] + 1],
        [mid, box[1] - 1, box[2] + 1, box[3] + 1],
      ].map((b) => {
        const p = intersect(
          featureCollection([
            feature(g.footprint),
            bboxPolygon(b as [number, number, number, number]),
          ]),
        );
        if (!p || p.geometry.type !== "Polygon")
          throw Error(
            "This centre cut cannot produce two single polygons. Use a surveyed split through the API.",
          );
        return p.geometry;
      });
    }
    if (mode === "MERGE") {
      const second = scene.geometries.find((x) => x.object_id === other);
      if (!second) throw Error("Select an adjacent unit");
      const merged = union(
        featureCollection([feature(g.footprint), feature(second.footprint)]),
      );
      if (!merged || merged.geometry.type !== "Polygon")
        throw Error("Selected units are not adjacent as a single polygon");
      polys = [merged.geometry];
      inputs.push(other);
      expected.push(second.id);
    }
    const result = await api<{ result: { outputs: { object_id: string }[] } }>(
      "/pipeline/changes",
      {
        operation: mode,
        object_ids: inputs,
        expected_geometry_ids: expected,
        evidence_id: evidenceId,
        reason,
        replacements: polys.map((p, i) => ({
          label: mode === "SPLIT" ? label + (i === 0 ? " A" : " B") : label,
          geometry: geometry(p),
        })),
      },
    );
    if (result.result.outputs[0])
      store.set({ selected: result.result.outputs[0].object_id });
  }
  return (
    <section className="governance">
      <Button
        variant="outline"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        Property case · {d?.state?.replaceAll("_", " ") || "Loading"}
      </Button>
      {open && (
        <div className="case-body">
          {q.error && <p role="alert">{q.error.message}</p>}
          {d && (
            <>
              <p className="muted">
                Prototype review ·{" "}
                {obj.is_synthetic
                  ? "Demo / Synthetic Dataset"
                  : "Provided records"}
              </p>
              <strong data-testid="workflow-state">
                {d.state.replaceAll("_", " ")}
              </strong>
              <p>{d.validation_reason}</p>
              {d.validation_job && (
                <p>
                  Validation job: {d.validation_job.status}
                  {d.validation_job.error_message
                    ? " · " + d.validation_job.error_message
                    : ""}
                </p>
              )}
              <div className="case-actions">
                {writer && obj.lifecycle === "ACTIVE" && (
                  <>
                    <Button
                      disabled={busy || !g}
                      onClick={() =>
                        act(
                          () => api("/pipeline/validate/" + obj.id, {}),
                          "Validation queued. Waiting for worker.",
                        )
                      }
                    >
                      Run validation
                    </Button>
                    <Button
                      variant="outline"
                      disabled={
                        busy ||
                        !d.validation_fresh ||
                        ![
                          "BUILDING",
                          "UNIT",
                          "SHARED",
                          "UNDERGROUND",
                          "EASEMENT",
                          "INFRASTRUCTURE",
                        ].includes(obj.kind)
                      }
                      onClick={() =>
                        act(
                          () => api("/ulpin/" + obj.id, {}),
                          "Proposed 3D ULPIN recorded.",
                        )
                      }
                    >
                      Record Proposed 3D ULPIN
                    </Button>
                    <Button
                      variant="outline"
                      disabled={
                        busy || !d.validation_fresh || !d.evidence.length
                      }
                      onClick={() =>
                        act(
                          () =>
                            api("/reviews", {
                              geometry_id: g!.id,
                              validation_job_id: d.validation_job!.id,
                            }),
                          "Submitted for officer review.",
                        )
                      }
                    >
                      Submit for review
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => begin("evidence")}
                    >
                      Add evidence
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => begin("right")}
                    >
                      Record right
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => begin("scope")}
                    >
                      Scope a right
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => begin("details")}
                    >
                      Update property details
                    </Button>
                    {obj.kind === "UNIT" && g && (
                      <>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => begin("REPLACE")}
                        >
                          Correct boundary
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => begin("SPLIT")}
                        >
                          Split unit
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => begin("MERGE")}
                        >
                          Merge units
                        </Button>
                      </>
                    )}
                  </>
                )}
                <Button
                  variant="outline"
                  onClick={() =>
                    saveJson(d, "property-case-" + obj.id + ".json")
                  }
                >
                  Download case report
                </Button>
              </div>
              {message && (
                <p role="status" className="case-message">
                  {message}
                </p>
              )}
              {mode && (
                <form
                  className="case-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(async () => {
                      if (["REPLACE", "SPLIT", "MERGE"].includes(mode))
                        return change();
                      if (mode === "evidence") {
                        if (!file) throw Error("Choose a source document");
                        const form = new FormData();
                        form.append("file", file);
                        form.append("intent", "evidence");
                        form.append("source_category", source);
                        form.append("is_synthetic", String(obj.is_synthetic));
                        const dataset = await api<{ id: string }>(
                          "/datasets",
                          form,
                        );
                        return api("/evidence", {
                          object_id: obj.id,
                          dataset_id: dataset.id,
                          description,
                        });
                      }
                      if (mode === "right")
                        return api("/rights", {
                          object_id: obj.id,
                          evidence_id: evidenceId,
                          right_type: rightType,
                          party_reference: party,
                          description,
                          is_synthetic: obj.is_synthetic,
                        });
                      if (mode === "scope")
                        return api("/governance/right-scopes", {
                          right_id: scopeRight,
                          related_object_id: other,
                          reason,
                        });
                      if (mode === "details")
                        return api(
                          "/governance/objects/" + obj.id + "/annotations",
                          {
                            display_label: label,
                            address: address || null,
                            land_use: landUse || null,
                            evidence_id: evidenceId,
                            reason,
                            expected_previous_id:
                              d.annotations.at(-1)?.id || null,
                          },
                        );
                    }, "Record saved; history preserved.");
                  }}
                >
                  <h4>
                    {mode === "REPLACE"
                      ? "Boundary revision"
                      : mode === "SPLIT"
                        ? "Split at footprint centre"
                        : mode === "MERGE"
                          ? "Merge adjacent units"
                          : mode === "right"
                            ? "Recorded right"
                            : mode === "scope"
                              ? "Explicit right scope"
                              : mode === "details"
                                ? "Provided property details"
                                : "Supporting evidence"}
                  </h4>
                  {mode === "evidence" ? (
                    <>
                      <label>
                        Source document
                        <input
                          aria-label="Source document"
                          type="file"
                          accept=".pdf,.png,.jpg,.jpeg"
                          required
                          onChange={(e) => setFile(e.target.files?.[0] || null)}
                        />
                      </label>
                      <label>
                        Source classification
                        <select
                          value={source}
                          onChange={(e) => setSource(e.target.value)}
                        >
                          {[
                            "MANUAL",
                            "SURVEY",
                            "APPROVED_PLAN",
                            "LIDAR",
                            "DRONE_IMAGERY",
                            "DEM_DSM",
                            "DERIVED",
                          ].map((x) => (
                            <option key={x}>{x}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Description
                        <textarea
                          aria-label="Evidence description"
                          required
                          minLength={3}
                          value={description}
                          onChange={(e) => setDescription(e.target.value)}
                        />
                      </label>
                    </>
                  ) : (
                    mode !== "scope" && (
                      <label>
                        Supporting evidence
                        <select
                          aria-label="Supporting evidence"
                          required
                          value={evidenceId}
                          onChange={(e) => setEvidenceId(e.target.value)}
                        >
                          <option value="">Select evidence</option>
                          {d.evidence.map((e) => (
                            <option key={e.id} value={e.id}>
                              {e.description}
                            </option>
                          ))}
                        </select>
                      </label>
                    )
                  )}
                  {mode === "right" && (
                    <>
                      <label>
                        Right type
                        <select
                          value={rightType}
                          onChange={(e) => setRightType(e.target.value)}
                        >
                          {[
                            "RECORDED_OWNERSHIP",
                            "SHARED_USE",
                            "ACCESS",
                            "EASEMENT",
                            "RESTRICTION",
                          ].map((x) => (
                            <option key={x}>{x}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Provided party reference
                        <input
                          required
                          value={party}
                          onChange={(e) => setParty(e.target.value)}
                        />
                      </label>
                      <label>
                        Description
                        <textarea
                          aria-label="Right description"
                          required
                          minLength={3}
                          value={description}
                          onChange={(e) => setDescription(e.target.value)}
                        />
                      </label>
                    </>
                  )}
                  {mode === "scope" && (
                    <label>
                      Recorded right
                      <select
                        required
                        value={scopeRight}
                        onChange={(e) => setScopeRight(e.target.value)}
                      >
                        <option value="">Select right</option>
                        {d.rights
                          .filter((r) => r.right_type !== "RECORDED_OWNERSHIP")
                          .map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.right_type} · {r.party_reference}
                            </option>
                          ))}
                      </select>
                    </label>
                  )}
                  {(mode === "MERGE" || mode === "scope") && (
                    <label>
                      Related space
                      <select
                        required
                        value={other}
                        onChange={(e) => setOther(e.target.value)}
                      >
                        <option value="">Select space</option>
                        {scene.objects
                          .filter(
                            (x) =>
                              x.id !== obj.id &&
                              x.lifecycle === "ACTIVE" &&
                              (mode === "scope" ||
                                (x.kind === "UNIT" &&
                                  x.parent_id === obj.parent_id)),
                          )
                          .map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.label} · {x.kind}
                            </option>
                          ))}
                      </select>
                    </label>
                  )}
                  {["REPLACE", "SPLIT", "MERGE", "details"].includes(mode) && (
                    <label>
                      Property label
                      <input
                        required
                        value={label}
                        onChange={(e) => setLabel(e.target.value)}
                      />
                    </label>
                  )}
                  {mode === "details" && (
                    <>
                      <label>
                        Provided address
                        <input
                          value={address}
                          onChange={(e) => setAddress(e.target.value)}
                        />
                      </label>
                      <label>
                        Provided land use
                        <input
                          value={landUse}
                          onChange={(e) => setLandUse(e.target.value)}
                        />
                      </label>
                    </>
                  )}
                  {mode === "REPLACE" && (
                    <label>
                      Boundary polygon · longitude, latitude
                      <textarea
                        aria-label="Boundary polygon"
                        className="geometry-input"
                        required
                        value={footprint}
                        onChange={(e) => setFootprint(e.target.value)}
                      />
                    </label>
                  )}
                  {["REPLACE", "SPLIT", "MERGE"].includes(mode) && (
                    <>
                      <p className="muted">
                        Explicit source coordinates. Saving creates a new draft.
                        Split and merge preserve mapped area and heights; rights
                        require separate review.
                      </p>
                      <label>
                        Lower elevation (m)
                        <input
                          aria-label="Lower elevation"
                          type="number"
                          step="any"
                          required
                          value={low}
                          onChange={(e) => setLow(e.target.value)}
                        />
                      </label>
                      <label>
                        Upper elevation (m)
                        <input
                          aria-label="Upper elevation"
                          type="number"
                          step="any"
                          required
                          value={high}
                          onChange={(e) => setHigh(e.target.value)}
                        />
                      </label>
                      <label>
                        Elevation reference
                        <input
                          required
                          value={datum}
                          onChange={(e) => setDatum(e.target.value)}
                        />
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={estimated}
                          onChange={(e) => setEstimated(e.target.checked)}
                        />{" "}
                        Height is estimated
                      </label>
                    </>
                  )}
                  {!["evidence", "right"].includes(mode) && (
                    <label>
                      Reason
                      <textarea
                        aria-label="Change reason"
                        minLength={5}
                        required
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                      />
                    </label>
                  )}
                  <div className="case-actions">
                    <Button type="submit" disabled={busy}>
                      Save record
                    </Button>
                    <Button
                      variant="outline"
                      type="button"
                      onClick={() => setMode("")}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
              {d.annotations.at(-1) && (
                <div className="case-record">
                  <strong>{d.annotations.at(-1)!.display_label}</strong>
                  <p>
                    {d.annotations.at(-1)!.address || "Address not supplied"}
                  </p>
                  <p>
                    {d.annotations.at(-1)!.land_use || "Land use not supplied"}
                  </p>
                </div>
              )}
              <h4>Validation findings</h4>
              {d.issues.map((i) => (
                <div className="case-record" key={i.id}>
                  <strong>
                    {i.severity} · {i.code}
                  </strong>
                  <p>{i.message}</p>
                  {typeof i.details.intersection_volume_m3 === "number" && (
                    <p>
                      Measured overlap:{" "}
                      {i.details.intersection_volume_m3.toFixed(4)} m³
                    </p>
                  )}
                  <p>
                    {String(
                      (
                        i.details.rule_definition as
                          { resolution_guidance?: string } | undefined
                      )?.resolution_guidance || "",
                    )}
                  </p>
                  <Button
                    variant="ghost"
                    onClick={() => store.set({ issue: i.id })}
                  >
                    Show affected geometry
                  </Button>
                </div>
              ))}
              <h4>Officer review</h4>
              {d.reviews.length === 0 && (
                <p className="muted">No review submitted.</p>
              )}
              {d.reviews.map((r) => (
                <ReviewDecision
                  key={r.id}
                  review={r}
                  eligible={officer && r.submitted_by !== member.id}
                  fresh={d.validation_fresh && r.geometry_id === g?.id}
                  onDone={() => client.invalidateQueries()}
                />
              ))}
              {d.decisions.map((r) => (
                <div className="case-record" key={r.id}>
                  <strong>{r.decision}</strong>
                  <p>{r.reason}</p>
                  <small>Reviewer {r.reviewer_id}</small>
                </div>
              ))}
              <h4>Recorded rights</h4>
              {d.rights.length === 0 && (
                <p className="muted">No rights supplied.</p>
              )}
              {d.rights.map((r) => (
                <div className="case-record" key={r.id}>
                  <strong>{r.right_type.replaceAll("_", " ")}</strong>
                  <p>
                    {r.party_reference} · {r.description}
                  </p>
                  <small>Evidence {r.evidence_id}</small>
                </div>
              ))}
              <h4>Geometry provenance</h4>
              {g && (
                <div className="case-record">
                  <strong>{g.source_category}</strong>
                  <p>{g.method}</p>
                  <p>{new Date(g.created_at).toLocaleString()}</p>
                  <p>
                    {g.confidence === null
                      ? "Confidence not supplied"
                      : g.source_category === "AI_ESTIMATE"
                        ? "Model confidence: " +
                          g.confidence +
                          " · " +
                          (g.confidence >= 0.8
                            ? "HIGH"
                            : g.confidence >= 0.5
                              ? "MEDIUM"
                              : "LOW")
                        : "Supplied source confidence: " +
                          g.confidence +
                          " (not model confidence)"}
                  </p>
                  {g.source_category === "AI_ESTIMATE" &&
                    g.confidence !== null && (
                      <small>
                        Display bands: HIGH ≥ 0.8, MEDIUM ≥ 0.5, LOW below 0.5.
                        Not calibrated survey accuracy.
                      </small>
                    )}
                </div>
              )}
              {d.attestations.map((a) => (
                <div className="case-record" key={a.id}>
                  {a.status} · {a.reason}
                  <small>Reviewer {a.actor_id}</small>
                </div>
              ))}
              <h4>Evidence</h4>
              {d.evidence.map((e) => (
                <div className="case-record" key={e.id}>
                  <strong>{e.description}</strong>
                  {d.sources
                    .filter((x) => x.id === e.dataset_id)
                    .map((x) => (
                      <p key={x.id}>
                        {x.filename} · {x.source_category} · {x.status}
                      </p>
                    ))}
                  <p>{new Date(e.created_at).toLocaleString()}</p>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      act(
                        () =>
                          download(
                            "/api/v1/datasets/" + e.dataset_id + "/original",
                            "evidence-" + e.id,
                          ),
                        "Source downloaded.",
                      )
                    }
                  >
                    Download source
                  </Button>
                </div>
              ))}
              <HistoryBrowser
                objectId={obj.id}
                viewer={member.role === "viewer"}
              />
              <h4>Workflow history · latest records</h4>
              {d.workflow.length === 0 && (
                <p className="muted">
                  No phase 4 transitions yet. Earlier events are retained in the
                  case report.
                </p>
              )}
              {d.workflow.map((e) => (
                <div key={e.id} className="case-record">
                  <strong>
                    {e.before_state} → {e.after_state}
                  </strong>
                  <p>{e.reason}</p>
                  <small>
                    {new Date(e.created_at).toLocaleString()} · {e.actor_id}
                  </small>
                </div>
              ))}
              <h4>Property changes</h4>
              {d.changes.map((c) => (
                <div className="case-record" key={c.id}>
                  <strong>{c.operation}</strong>
                  <p>{c.reason}</p>
                  {c.members.map((m) => (
                    <small key={m.direction + m.geometry_id}>
                      {m.direction}: {m.geometry_id}
                    </small>
                  ))}
                </div>
              ))}
              <details>
                <summary>
                  Preserved geometry versions ({d.geometry_versions.length})
                </summary>
                {d.geometry_versions.map((v) => (
                  <div className="case-record" key={v.id}>
                    <strong>Version {v.version}</strong>
                    <p>{v.method}</p>
                    <small>{v.id}</small>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        saveJson(v, "geometry-v" + v.version + ".json")
                      }
                    >
                      Download geometry
                    </Button>
                  </div>
                ))}
              </details>
            </>
          )}
        </div>
      )}
    </section>
  );
}
function ReviewDecision({
  review,
  eligible,
  fresh,
  onDone,
}: {
  review: Review;
  eligible: boolean;
  fresh: boolean;
  onDone: () => Promise<unknown>;
}) {
  const [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function decide(decision: string) {
    setBusy(true);
    setError("");
    try {
      await api("/reviews/" + review.id + "/decisions", { decision, reason });
      await onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="case-record">
      <strong>{review.status.replaceAll("_", " ")}</strong>
      <small>{new Date(review.created_at).toLocaleString()}</small>
      {review.status === "SUBMITTED" && eligible && (
        <>
          <label>
            Decision reason
            <textarea
              aria-label="Decision reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="case-actions">
            <Button
              disabled={busy || reason.trim().length < 5 || !fresh}
              onClick={() => decide("ACCEPTED_PROTOTYPE")}
            >
              Accept prototype
            </Button>
            <Button
              variant="outline"
              disabled={busy || reason.trim().length < 5}
              onClick={() => decide("RETURNED")}
            >
              Return for correction
            </Button>
          </div>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export function ReviewQueue() {
  const store = useWorkspace();
  const q = useQuery({
    queryKey: ["review-queue"],
    queryFn: () =>
      api<{
        result: {
          items: (Review & {
            object_id: string;
            object_label: string;
            parcel_id: string;
          })[];
        };
      }>("/governance/review-queue"),
    refetchInterval: 5000,
  });
  return (
    <div className="card mb-5">
      <h2>Officer review queue</h2>
      {q.error && <p role="alert">{q.error.message}</p>}
      {q.data?.result.items.length === 0 && (
        <p className="muted">No submitted cases.</p>
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Property</th>
            <th>Status</th>
            <th>Submitted</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {q.data?.result.items.map((r) => (
            <tr key={r.id}>
              <td>{r.object_label}</td>
              <td>{r.status.replaceAll("_", " ")}</td>
              <td>{new Date(r.created_at).toLocaleString()}</td>
              <td>
                <Button
                  variant="outline"
                  onClick={() =>
                    store.set({
                      page: "Map",
                      parcel: r.parcel_id,
                      selected: r.object_id,
                      floor: null,
                      issue: null,
                    })
                  }
                >
                  Open property case
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ReportView({ report }: { report: Record<string, unknown> }) {
  const [kind, setKind] = useState("Property");
  const sections: Record<string, string[]> = {
    Property: [
      "object",
      "ancestors",
      "identity_versions",
      "rights",
      "evidence",
      "validation_job",
      "reviews",
    ],
    Validation: ["validation_job", "issues"],
    Provenance: ["geometry", "sources", "attestations"],
    Review: ["reviews", "decisions", "workflow"],
    "Change history": ["changes", "workflow", "audit"],
  };
  const visible = Object.fromEntries([
    ...["object", "state", "legal_effect", "pagination"].map((k) => [
      k,
      report[k],
    ]),
    ...sections[kind].map((k) => [k, report[k]]),
  ]);
  return (
    <div className="case-report">
      <div className="case-actions">
        <label>
          Report type{" "}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.keys(sections).map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          onClick={() =>
            saveJson(
              visible,
              "astra-" +
                kind.toLowerCase().replaceAll(" ", "-") +
                "-report.json",
            )
          }
        >
          Download selected report
        </Button>
        <Button variant="outline" onClick={() => window.print()}>
          Print report
        </Button>
      </div>
      <h2>{kind} report</h2>
      <p>Proposed 3D ULPIN · prototype records · no legal title decision</p>
      <p className="muted">
        This report contains recent records. Use Browse complete property
        history in the property case to page through earlier records. Downloaded
        reports include their pagination limits.
      </p>
      {sections[kind].map((k) => (
        <section key={k}>
          <h3 className="section-title">{k.replaceAll("_", " ")}</h3>
          {(Array.isArray(report[k])
            ? report[k]
            : report[k]
              ? [report[k]]
              : []
          ).map((row: Record<string, unknown>, index: number) => (
            <dl className="report-record" key={index}>
              {Object.entries(row)
                .filter(
                  ([key]) =>
                    ![
                      "footprint",
                      "transformation",
                      "snapshot",
                      "inspection",
                      "parameters",
                      "identity_inputs",
                    ].includes(key),
                )
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>
                      {value === null ? (
                        "Not supplied"
                      ) : typeof value === "object" ? (
                        <details>
                          <summary>View recorded details</summary>
                          <pre>{JSON.stringify(value, null, 2)}</pre>
                        </details>
                      ) : (
                        String(value)
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
          ))}
          {Array.isArray(report[k]) &&
            (report[k] as unknown[]).length === 0 && (
              <p className="muted">No records supplied.</p>
            )}
        </section>
      ))}
    </div>
  );
}

export function AdminMembers() {
  const client = useQueryClient(),
    [selected, setSelected] = useState(""),
    [role, setRole] = useState("viewer"),
    [active, setActive] = useState(true),
    [reason, setReason] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const q = useQuery({
    queryKey: ["members"],
    queryFn: () =>
      api<{
        result: { items: { id: string; role: string; active: boolean }[] };
      }>("/governance/members"),
  });
  return (
    <div className="card mt-6 max-w-xl">
      <h2>Project membership</h2>
      <p className="muted">
        Existing project members. Identity accounts are managed in Supabase
        Auth.
      </p>
      {q.error && <p role="alert">{q.error.message}</p>}
      <form
        className="case-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api("/governance/members/" + selected, {
              role,
              active,
              reason,
            });
            setMessage("Membership updated and audited.");
            await client.invalidateQueries({ queryKey: ["members"] });
          } catch (error) {
            setMessage(String(error));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Member
          <select
            required
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              const m = q.data?.result.items.find(
                (x) => x.id === e.target.value,
              );
              if (m) {
                setRole(m.role);
                setActive(m.active);
              }
            }}
          >
            <option value="">Select existing member</option>
            {q.data?.result.items.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id} · {m.role} · {m.active ? "active" : "inactive"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Project role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {["admin", "surveyor", "officer", "viewer"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />{" "}
          Active membership
        </label>
        <label>
          Reason
          <textarea
            required
            minLength={5}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <Button disabled={busy}>Save membership</Button>
        {message && <p role="status">{message}</p>}
      </form>
    </div>
  );
}

function HistoryBrowser({
  objectId,
  viewer,
}: {
  objectId: string;
  viewer: boolean;
}) {
  const [open, setOpen] = useState(false),
    [kind, setKind] = useState("workflow"),
    [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["history-page", objectId, kind, offset],
    queryFn: () =>
      api<{
        result: {
          items: Record<string, unknown>[];
          next_offset: number | null;
        };
      }>(
        "/governance/objects/" +
          objectId +
          "/history?kind=" +
          kind +
          "&offset=" +
          offset +
          "&limit=20",
      ),
    enabled: open,
  });
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Browse complete property history</summary>
      <label>
        History records
        <select
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setOffset(0);
          }}
        >
          {[
            "workflow",
            "geometry_versions",
            "evidence",
            "rights",
            "reviews",
            "annotations",
            "changes",
            ...(viewer ? [] : ["audit"]),
          ].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </label>
      {q.isLoading && <p>Loading history…</p>}
      {q.error && <p role="alert">{q.error.message}</p>}
      {q.data?.result.items.map((r, i) => (
        <div className="case-record" key={String(r.id || i)}>
          <strong>
            {String(
              r.action ||
                r.after_state ||
                r.operation ||
                r.right_type ||
                r.display_label ||
                (r.version !== undefined
                  ? "Version " + r.version
                  : kind.replaceAll("_", " ")),
            )}
          </strong>
          <p>
            {String(r.reason || r.method || r.description || r.status || "")}
          </p>
          <small>
            {String(r.created_at)} ·{" "}
            {String(r.actor_id || r.created_by || r.submitted_by || "")}
          </small>
          <Button
            variant="ghost"
            onClick={() => saveJson(r, "history-" + String(r.id) + ".json")}
          >
            Download record
          </Button>
        </div>
      ))}
      <div className="case-actions">
        <Button
          variant="outline"
          disabled={!offset || q.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          Newer records
        </Button>
        <Button
          variant="outline"
          disabled={q.data?.result.next_offset == null || q.isFetching}
          onClick={() => setOffset(q.data!.result.next_offset!)}
        >
          Older records
        </Button>
      </div>
    </details>
  );
}
