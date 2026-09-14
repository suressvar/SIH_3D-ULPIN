"use client";

import { appearanceActive } from "@/lib/view-math";
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Home,
  Map,
  Building2,
  ShieldCheck,
  FileText,
  Settings,
  Search,
  LogOut,
  RotateCcw,
  Layers,
  Scissors,
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  PanelRight,
  Download,
  Copy,
  Plus,
  Minus,
  Navigation,
} from "lucide-react";
import {
  GovernancePanel,
  ReviewQueue,
  ReportView,
  AdminMembers,
} from "./governance";
import { Auth, supabase, type Member } from "./auth";
import { Button } from "./ui/button";
import { api, download, setToken, ApiError } from "@/lib/api";
import { AssetPreview } from "./asset-preview";
import { useWorkspace } from "@/lib/store";
import type {
  SpatialObject,
  Scene,
  Issue,
  IssueDetail,
  RecordData,
} from "@/lib/types";

const Map3D = dynamic(() => import("./map3d"), {
  ssr: false,
  loading: () => <div className="empty">Loading 3D workspace…</div>,
});
const Map2D = dynamic(() => import("./map2d"), {
  ssr: false,
  loading: () => <div className="empty">Loading 2D workspace…</div>,
});

type Envelope<T> = { result: T };
type Overview = {
  counts: Record<string, number>;
  pending_reviews: number;
  validation_issues: number;
  suggestions: number;
  jobs: RecordData[];
  recent_changes: RecordData[];
};

export const text = (v: unknown) =>
  v === null || v === undefined ? "Not recorded" : String(v);

export function Badge({
  children,
  severity = "",
}: {
  children: React.ReactNode;
  severity?: string;
}) {
  return <span className={"badge " + severity}>{children}</span>;
}

function Empty() {
  return <p className="empty">No records available</p>;
}

function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <p role="alert" className="error">
      {String(error)}
    </p>
  ) : null;
}

export default function Workspace() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30000,
            retry: (count, error) =>
              count < 1 && error instanceof ApiError && error.status >= 500,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );
  const [member, setMember] = useState<Member | null>(null);
  useEffect(() => {
    if (!supabase) return;
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (session) setToken(session.access_token);
      if (event === "SIGNED_OUT") {
        setToken("");
        client.clear();
        setMember(null);
      }
    });
    return () => data.subscription.unsubscribe();
  }, [client]);
  return (
    <QueryClientProvider client={client}>
      {member ? (
        <Shell
          member={member}
          logout={async () => {
            await supabase?.auth.signOut();
            setToken("");
            client.clear();
            setMember(null);
          }}
        />
      ) : (
        <Auth onMember={setMember} />
      )}
    </QueryClientProvider>
  );
}

function Shell({ member, logout }: { member: Member; logout: () => void }) {
  const s = useWorkspace();
  const [q, setQ] = useState(""),
    [searchOpen, setOpen] = useState(false),
    [debounced, setDebounced] = useState("");
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        search.current?.focus();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () =>
      api<Envelope<{ items: SpatialObject[] }>>(
        "/workspace/search?q=" + encodeURIComponent(debounced),
      ),
    enabled: searchOpen,
  });

  function choose(o: SpatialObject) {
    s.set({
      page: "Map",
      parcel: o.parcel_id || o.id,
      selected: o.id,
      floor: o.kind === "FLOOR" ? o.id : null,
      issue: null,
    });
    setOpen(false);
  }

  const nav = [
    ["Home", Home],
    ["Map", Map],
    ["Buildings", Building2],
    ["Validation", ShieldCheck],
    ["Reports", FileText],
    ["Settings", Settings],
  ] as const;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <svg className="astra-symbol" viewBox="0 0 40 40" aria-hidden="true">
            <path
              d="M4 34 19 5h3l15 29h-7L20.5 14 11 34Z"
              fill="currentColor"
            />
          </svg>
          <span className="brand-name">ASTRA 3D MAP</span>
        </div>
        <nav className="nav" aria-label="Main navigation">
          {nav.map(([name, Icon]) => (
            <button
              key={name}
              title={name}
              className={s.page === name ? "active" : ""}
              aria-current={s.page === name ? "page" : undefined}
              onClick={() => s.set({ page: name })}
            >
              <Icon size={22} strokeWidth={1.6} />
              <span className="nav-label">{name}</span>
            </button>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="topbar-title">3D Property Mapping</div>
          <div className="search">
            <Search className="search-icon" size={15} />
            <input
              ref={search}
              aria-label="Global search"
              placeholder="Search ULPIN, address or location…"
              value={q}
              onFocus={() => setOpen(true)}
              onChange={(e) => setQ(e.target.value)}
            />
            <kbd className="search-shortcut">⌘ K</kbd>
            {searchOpen && (
              <div className="search-results" aria-label="Search results">
                <small>Records · location search: longitude, latitude</small>
                {results.isLoading && <p>Searching…</p>}
                <ErrorNotice error={results.error} />
                {results.data?.result.items.map((o) => (
                  <button key={o.id} onClick={() => choose(o)}>
                    <strong>{o.label}</strong>
                    <small>
                      {o.kind} · {o.id.slice(0, 8)} ·{" "}
                      {o.is_synthetic ? "Synthetic" : "Source record"}
                    </small>
                  </button>
                ))}
                {results.data?.result.items.length === 0 && <Empty />}
              </div>
            )}
          </div>
          <div className="profile">
            <span className="avatar">
              {member.role.slice(0, 1).toUpperCase()}
            </span>
            <span className="role-label">
              {member.role}
              <br />
              <small>Project member</small>
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={logout}
              aria-label="Sign out"
            >
              <LogOut size={15} />
            </Button>
          </div>
        </header>
        <div className="content">
          {s.page === "Home" ? (
            <OverviewPage choose={choose} />
          ) : s.page === "Map" ? (
            <MapPage member={member} choose={choose} />
          ) : s.page === "Buildings" ? (
            <Buildings choose={choose} />
          ) : s.page === "Validation" ? (
            <ValidationPage />
          ) : s.page === "Reports" ? (
            <Reports />
          ) : (
            <SettingsPage member={member} />
          )}
        </div>
      </main>
    </div>
  );
}

function OverviewPage({ choose }: { choose: (o: SpatialObject) => void }) {
  const d = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Envelope<Overview>>("/workspace/overview"),
    refetchInterval: 10000,
  });
  const parcels = useQuery({
    queryKey: ["parcels"],
    queryFn: () => api<SpatialObject[]>("/parcels"),
  });
  const v = d.data?.result;
  return (
    <section className="overview">
      <div className="page-head">
        <div>
          <p className="eyebrow">OPERATIONS OVERVIEW</p>
          <h1>Property workspace</h1>
          <p className="muted mt-2">
            Explore vertical spaces and the records behind their boundaries.
          </p>
        </div>
        <Button
          disabled={!parcels.data?.length}
          onClick={() => choose(parcels.data![0])}
        >
          Open spatial workspace <ArrowUpRight size={15} />
        </Button>
      </div>
      <ErrorNotice error={d.error} />
      {v ? (
        <>
          <div className="stats">
            {[
              ["Property units", v.counts.UNIT || 0],
              ["Pending reviews", v.pending_reviews],
              ["Open validation issues", v.validation_issues],
              ["Extraction suggestions", v.suggestions],
            ].map(([label, n]) => (
              <div className="card" key={label}>
                <small>{label}</small>
                <div className="stat-value">{n}</div>
                <small>Recorded in this workspace</small>
              </div>
            ))}
          </div>
          <div className="grid-two">
            <div className="card">
              <h2>Mapped parcels</h2>
              {parcels.data?.length ? (
                parcels.data.map((o) => (
                  <button
                    className="row w-full text-left"
                    key={o.id}
                    onClick={() => choose(o)}
                  >
                    <span>
                      <strong>{o.label}</strong>
                      <br />
                      <small>
                        {o.existing_ulpin || "Parent ULPIN not supplied"}
                      </small>
                    </span>
                    <ChevronRight size={16} />
                  </button>
                ))
              ) : (
                <Empty />
              )}
            </div>
            <div className="card">
              <h2>Processing activity</h2>
              {v.jobs.length ? (
                v.jobs.slice(0, 6).map((j) => (
                  <div className="row" key={text(j.id)}>
                    <span>
                      {text(j.kind).replaceAll("_", " ")}
                      <br />
                      <small>
                        {new Date(text(j.created_at)).toLocaleString()}
                      </small>
                    </span>
                    <Badge>{text(j.status)}</Badge>
                  </div>
                ))
              ) : (
                <Empty />
              )}
            </div>
            <div className="card">
              <h2>Recent changes</h2>
              {v.recent_changes.length ? (
                v.recent_changes.slice(0, 7).map((a) => (
                  <div className="row" key={text(a.id)}>
                    <span>
                      {text(a.action).replaceAll("_", " ")}
                      <br />
                      <small>
                        {text(a.entity_type)} ·{" "}
                        {new Date(text(a.created_at)).toLocaleString()}
                      </small>
                    </span>
                  </div>
                ))
              ) : (
                <Empty />
              )}
            </div>
            <div className="card">
              <p className="eyebrow">DATA WITH CONTEXT</p>
              <h2 className="mt-3">Geometry is one part of the record.</h2>
              <p className="muted leading-7 mt-4">
                Inspect sources, validation, and review status alongside every
                mapped volume. Synthetic records are labelled throughout the
                workspace.
              </p>
              <p className="notice mt-6">
                Proposed 3D ULPIN is this project&apos;s prototype encoding. It
                is not an official government 3D standard.
              </p>
            </div>
          </div>
        </>
      ) : d.isLoading ? (
        <p>Loading records…</p>
      ) : (
        <Empty />
      )}
    </section>
  );
}

function Buildings({ choose }: { choose: (o: SpatialObject) => void }) {
  const q = useQuery({
    queryKey: ["buildings"],
    queryFn: () => api<SpatialObject[]>("/buildings?limit=100"),
  });
  return (
    <section className="list-page">
      <div className="page-head">
        <div>
          <p className="eyebrow">PROPERTY REGISTER</p>
          <h1>Buildings</h1>
        </div>
        <Badge>Up to 100 records</Badge>
      </div>
      <ErrorNotice error={q.error} />
      <div className="card">
        {q.data?.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Building</th>
                <th>Parcel</th>
                <th>Source designation</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.map((o) => (
                <tr key={o.id}>
                  <td>{o.label}</td>
                  <td>{o.parcel_id?.slice(0, 8)}</td>
                  <td>
                    {o.is_synthetic
                      ? "Demo / Synthetic Dataset"
                      : "Provided record"}
                  </td>
                  <td>
                    <Button variant="outline" onClick={() => choose(o)}>
                      Explore
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty />
        )}
      </div>
    </section>
  );
}

function ValidationPage() {
  const q = useQuery({
    queryKey: ["issues"],
    queryFn: () => api<Envelope<{ items: Issue[] }>>("/workspace/issues"),
    refetchInterval: 5000,
  });
  const s = useWorkspace();
  return (
    <section className="list-page">
      <div className="page-head">
        <div>
          <p className="eyebrow">SPATIAL QUALITY</p>
          <h1>Validation workspace</h1>
        </div>
        <Badge>Latest 100 findings · includes history</Badge>
      </div>
      <ReviewQueue />
      <ErrorNotice error={q.error} />
      <div className="card">
        {q.data?.result.items.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Affected property</th>
                <th>Rule</th>
                <th>Severity</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.result.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.object_label}</td>
                  <td>{i.code.replaceAll("_", " ")}</td>
                  <td>
                    <Badge severity={i.severity}>{i.severity}</Badge>
                  </td>
                  <td>{i.status}</td>
                  <td>
                    <Button
                      variant="outline"
                      onClick={() =>
                        s.set({
                          page: "Map",
                          parcel: i.parcel_id,
                          selected: i.object_id,
                          issue: i.id,
                          floor: null,
                        })
                      }
                    >
                      Inspect conflict
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty />
        )}
      </div>
    </section>
  );
}

function MiniParcel({ scene }: { scene: Scene }) {
  const g = scene.geometries.find(
    (g) => scene.objects.find((o) => o.id === g.object_id)?.kind === "PARCEL",
  );
  if (!g) return null;
  const coords = g.footprint.coordinates[0];
  const xs = coords.map((p) => p[0]),
    ys = coords.map((p) => p[1]);
  const minx = Math.min(...xs),
    miny = Math.min(...ys),
    dx = Math.max(...xs) - minx,
    dy = Math.max(...ys) - miny;
  return (
    <svg
      aria-label="Parcel footprint context"
      viewBox="0 0 180 110"
      className="w-full my-4 bg-stone-50 rounded"
    >
      <polygon
        points={coords
          .map((p) =>
            [
              ((p[0] - minx) / dx) * 130 + 25,
              100 - ((p[1] - miny) / dy) * 90,
            ].join(","),
          )
          .join(" ")}
        fill="#e4eee0"
        stroke="#65825d"
      />
      {scene.geometries
        .filter(
          (g) =>
            scene.objects.find((o) => o.id === g.object_id)?.kind ===
            "BUILDING",
        )
        .map((g) => (
          <polygon
            key={g.id}
            points={g.footprint.coordinates[0]
              .map((p) =>
                [
                  ((p[0] - minx) / dx) * 130 + 25,
                  100 - ((p[1] - miny) / dy) * 90,
                ].join(","),
              )
              .join(" ")}
            fill="#8ca986"
            stroke="#54704f"
          />
        ))}
    </svg>
  );
}

function MapPage({
  member,
  choose,
}: {
  member: Member;
  choose: (o: SpatialObject) => void;
}) {
  const s = useWorkspace();
  const [panel, setPanel] = useState(false);
  const [sitePreview, setSitePreview] = useState(true);
  const [showOtherSpaces, setShowOtherSpaces] = useState(false);
  const parcels = useQuery({
    queryKey: ["parcels"],
    queryFn: () => api<SpatialObject[]>("/parcels"),
  });
  const q = useQuery({
    queryKey: ["scene", s.parcel],
    queryFn: () => api<Envelope<Scene>>("/workspace/scene/" + s.parcel),
    enabled: !!s.parcel,
  });
  const conflict = useQuery({
    queryKey: ["issue", s.issue],
    queryFn: () => api<Envelope<IssueDetail>>("/pipeline/issues/" + s.issue),
    enabled: !!s.issue,
  });
  const scene = q.data?.result;

  if (!s.parcel)
    return (
      <section className="list-page">
        <h1>Select a parcel</h1>
        <div className="card mt-5">
          {parcels.data?.map((o) => (
            <button className="row w-full" key={o.id} onClick={() => choose(o)}>
              {o.label}
              <ChevronRight size={16} />
            </button>
          ))}
          {!parcels.data?.length && <Empty />}
        </div>
      </section>
    );

  if (!scene)
    return (
      <section className="list-page">
        <ErrorNotice error={q.error} />
        {q.isLoading ? "Loading spatial records…" : "No scene available"}
      </section>
    );

  const obj =
      scene.objects.find((o) => o.id === s.selected) || scene.objects[0],
    parcel = scene.objects.find((o) => o.kind === "PARCEL")!,
    pg = scene.geometries.find((g) => g.object_id === parcel.id);
  const floors = scene.objects
    .filter(
      (o) =>
        o.kind === "FLOOR" &&
        (obj.kind !== "BUILDING" || o.parent_id === obj.id),
    )
    .sort((a, b) => (b.floor_number || 0) - (a.floor_number || 0));
  const underground = scene.objects.filter((o) => o.kind === "UNDERGROUND");
  const exterior = appearanceActive(scene, s);

  return (
    <section className="map-page">
      <div className="map-header">
        <div>
          <p className="eyebrow">SPATIAL EXPLORER</p>
          <h2>{obj.label.replace("Demo / Synthetic Dataset — ", "")}</h2>
        </div>
        <div className="flex gap-2">
          <Badge>
            {parcel.is_synthetic
              ? "Demo / Synthetic Dataset"
              : "Provided spatial records"}
          </Badge>
          <Button
            className="mobile-only"
            variant="outline"
            size="icon"
            aria-label="Toggle property panel"
            onClick={() => setPanel(!panel)}
          >
            <PanelRight size={16} />
          </Button>
        </div>
      </div>
      {s.notice && (
        <p role="status" className="fallback-notice">
          {s.notice}
        </p>
      )}
      <div className={"map-layout " + (panel ? "show-panel" : "")}>
        <aside className="context">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => s.set({ parcel: null, selected: null })}
          >
            <ArrowLeft size={13} /> Back to parcels
          </Button>
          <h3 className="mt-6 context-heading">Parcel context</h3>
          <dl className="meta parcel-facts">
            <dt>Parent ULPIN</dt>
            <dd>{parcel.existing_ulpin || "Not supplied"}</dd>
            <dt>Location · longitude, latitude</dt>
            <dd>
              {pg?.footprint.coordinates[0][0]
                .map((n) => n.toFixed(5))
                .join(", ")}
            </dd>
            <dt>Plot area</dt>
            <dd>{pg?.area_m2.toFixed(2)} m²</dd>
            <dt>Land use</dt>
            <dd>Not recorded</dd>
          </dl>
          <div className="parcel-preview">
            <div className="preview-switch">
              <button
                aria-pressed={!sitePreview}
                onClick={() => setSitePreview(false)}
              >
                Footprint
              </button>
              <button
                aria-pressed={sitePreview}
                onClick={() => setSitePreview(true)}
                disabled={!scene.asset?.files["site-preview.png"]}
              >
                Site model
              </button>
            </div>
            {sitePreview && scene.asset?.files["site-preview.png"] ? (
              <AssetPreview
                url={scene.asset.files["site-preview.png"]}
                alt="Illustrative synthetic site model, not satellite imagery"
              />
            ) : (
              <MiniParcel scene={scene} />
            )}
            <small>
              {" "}
              {sitePreview && scene.asset?.files["site-preview.png"]
                ? "Illustrative site · synthetic"
                : "Recorded parcel footprint"}
            </small>
          </div>
          <h3 className="section-title">Buildings on this parcel</h3>
          {scene.objects
            .filter(
              (o) =>
                o.kind === "BUILDING" ||
                (showOtherSpaces &&
                  ["PARCEL", "UNDERGROUND", "SHARED"].includes(o.kind)),
            )
            .map((o) => (
              <button
                key={o.id}
                className={
                  "tree-item context-object " +
                  (o.kind === "BUILDING" ? "context-building " : "") +
                  (s.selected === o.id ? "selected" : "")
                }
                onClick={() =>
                  s.set({ selected: o.id, issue: null, floor: null })
                }
              >
                {o.kind === "BUILDING" &&
                  scene.asset?.files["appearance.png"] && (
                    <AssetPreview
                      url={scene.asset.files["appearance.png"]}
                      alt="Illustrative building preview"
                    />
                  )}
                <span>
                  {o.kind === "BUILDING" ? "Building " : ""}
                  {o.label.replace("Demo / Synthetic Dataset — ", "")}
                  <small>
                    {o.kind === "BUILDING"
                      ? scene.objects.filter(
                          (item) =>
                            item.kind === "FLOOR" &&
                            item.parent_id === o.id &&
                            item.semantic_type !== "ROOF",
                        ).length +
                        " floors · " +
                        scene.objects.filter(
                          (item) =>
                            item.kind === "UNIT" &&
                            scene.objects.some(
                              (f) =>
                                f.id === item.parent_id && f.parent_id === o.id,
                            ),
                        ).length +
                        " units"
                      : o.kind}
                  </small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          <button
            className="other-spaces-toggle"
            onClick={() => setShowOtherSpaces(!showOtherSpaces)}
            aria-expanded={showOtherSpaces}
          >
            {showOtherSpaces
              ? "Hide other spaces"
              : "Parcel, shared & underground spaces"}{" "}
            <ChevronRight size={14} />
          </button>
        </aside>
        <div className="workspace-view">
          {s.mode === "3D" ? (
            <Map3D scene={scene} conflict={conflict.data?.result} />
          ) : (
            <Map2D scene={scene} conflict={conflict.data?.result} />
          )}
          <div className="viewer-tools">
            <div className="tool-group">
              {(["3D", "2D"] as const).map((m) => (
                <Button
                  key={m}
                  variant="ghost"
                  size="sm"
                  aria-pressed={s.mode === m}
                  onClick={() => s.set({ mode: m })}
                >
                  {m}
                </Button>
              ))}
            </div>
            <div className="tool-group">
              <Button
                variant="ghost"
                size="sm"
                aria-label="Exploded floors"
                aria-pressed={s.exploded}
                disabled={s.mode === "2D"}
                onClick={() => s.set({ exploded: !s.exploded })}
              >
                <Layers size={14} />
                {s.exploded ? "Exploded" : "Normal"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Cross-section"
                aria-pressed={s.slice}
                disabled={
                  s.mode === "2D" || !scene.asset || s.performance === "Low-end"
                }
                title={
                  !scene.asset
                    ? "Generate 3D assets to slice volumes"
                    : "Slice generated volume geometry"
                }
                onClick={() => s.set({ slice: !s.slice })}
              >
                <Scissors size={14} />
                Slice
              </Button>
            </div>
            <div className="tool-group">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Original north control"
                title="Reset view north"
                onClick={() => s.set({ reset: s.reset + 1, zoom: 0 })}
              >
                <RotateCcw size={14} />
                <span className="text-xs">N</span>
              </Button>
              <select
                aria-label="Performance mode"
                value={s.performance}
                onChange={(e) =>
                  s.set({
                    performance: e.target.value as "Standard" | "Low-end",
                    ...(e.target.value === "Low-end"
                      ? ({
                          mode: "2D",
                          notice:
                            "Low-end mode: 2D view preferred. Property records remain available; 3D can be opened when supported.",
                        } as const)
                      : {}),
                  })
                }
              >
                <option>Standard</option>
                <option>Low-end</option>
              </select>
            </div>
          </div>
          <div className="camera-controls">
            <button
              title="Reset view north"
              aria-label="Reset view north"
              onClick={() => s.set({ reset: s.reset + 1, zoom: 0 })}
            >
              <Navigation size={21} />
              <small>N</small>
            </button>
            <div>
              <button
                aria-label="Zoom in"
                onClick={() => s.set({ zoom: s.zoom + 1 })}
              >
                <Plus size={20} />
              </button>
              <button
                aria-label="Zoom out"
                onClick={() => s.set({ zoom: s.zoom - 1 })}
              >
                <Minus size={20} />
              </button>
            </div>
          </div>
          <div className="floors" aria-label="Floor selector">
            <button
              aria-pressed={!s.floor}
              onClick={() => s.set({ floor: null })}
            >
              All
            </button>
            {floors.map((f) => (
              <button
                key={f.id}
                title={f.label}
                aria-label={"Select " + f.label}
                aria-pressed={s.floor === f.id}
                onClick={() =>
                  s.set({ floor: f.id, selected: f.id, issue: null })
                }
              >
                {f.semantic_type === "ROOF"
                  ? "Roof"
                  : f.floor_number === null
                    ? f.label
                    : f.floor_number < 0
                      ? "B" + Math.abs(f.floor_number)
                      : f.floor_number === 0
                        ? "GF"
                        : "F" + f.floor_number}
              </button>
            ))}
            {underground.map((o) => (
              <button
                key={o.id}
                title={o.label}
                onClick={() =>
                  s.set({ selected: o.id, floor: null, issue: null })
                }
              >
                {o.label.replace("Demo / Synthetic Dataset — ", "").slice(0, 8)}
              </button>
            ))}
          </div>
          {s.slice && s.mode === "3D" && (
            <label className="slice-control">
              Cross-section position · view only
              <input
                aria-label="Slice position"
                type="range"
                min="-30"
                max="30"
                value={s.slicePosition}
                onChange={(e) =>
                  s.set({ slicePosition: Number(e.target.value) })
                }
              />
            </label>
          )}
          <div className="viewer-footer">
            <div className="legend">
              <span>▱ Parcel boundary</span>
              <span>
                ▰{" "}
                {exterior
                  ? "Illustrative surrounding buildings"
                  : "Property volumes · source geometry"}
              </span>
              <span>▰ Amber / red · validation finding</span>
            </div>
            <div>
              {exterior && s.mode === "3D"
                ? "Illustrative exterior & context"
                : "Stored cadastral geometry"}
              <br />
              {parcel.is_synthetic
                ? "Demo / Synthetic Dataset"
                : "Source records"}
            </div>
          </div>
        </div>
        <Inspector scene={scene} obj={obj} member={member} />
      </div>
    </section>
  );
}

function Inspector({
  scene,
  obj,
  member,
}: {
  scene: Scene;
  obj: SpatialObject;
  member: Member;
}) {
  const [tab, setTab] = useState("Overview"),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const s = useWorkspace(),
    client = useQueryClient();
  const g = scene.geometries.find((g) => g.object_id === obj.id);
  const rights = useQuery({
    queryKey: ["rights", obj.id],
    queryFn: () => api<RecordData[]>("/rights?object_id=" + obj.id),
  });
  const evidence = useQuery({
    queryKey: ["evidence", obj.id],
    queryFn: () => api<RecordData[]>("/evidence?object_id=" + obj.id),
  });
  const status = useQuery({
    queryKey: ["status", g?.id],
    queryFn: () =>
      api<Envelope<RecordData>>("/pipeline/geometry/" + g!.id + "/status"),
    enabled: !!g,
    refetchInterval: 5000,
  });
  const issues = useQuery({
    queryKey: ["issues"],
    queryFn: () => api<Envelope<{ items: Issue[] }>>("/workspace/issues"),
    refetchInterval: 5000,
  });
  const history = useQuery({
    queryKey: ["history", obj.id],
    queryFn: () => api<{ items: RecordData[] }>("/pipeline/history/" + obj.id),
  });
  useEffect(() => {
    setMessage("");
    setTab(s.issue ? "Validation" : "Overview");
  }, [obj.id, s.issue]);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
      await client.invalidateQueries();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  }

  const children = scene.objects.filter((o) => o.parent_id === obj.id),
    floorIds = new Set(
      children.filter((o) => o.kind === "FLOOR").map((o) => o.id),
    );
  const units = scene.objects.filter(
    (o) =>
      o.kind === "UNIT" &&
      (o.parent_id === obj.id || floorIds.has(o.parent_id || "")),
  );
  const selectedIssue = issues.data?.result.items.find((i) => i.id === s.issue);
  const modelDownload =
    scene.asset && g && scene.asset.snapshot[obj.id] === g.id
      ? scene.asset.files[obj.id + ".glb"]
      : undefined;
  const wholeModelDownload =
    ["PARCEL", "BUILDING"].includes(obj.kind) &&
    scene.asset &&
    scene.geometries.every(
      (item) => scene.asset!.snapshot[item.object_id] === item.id,
    )
      ? scene.asset.files["scene.glb"]
      : undefined;
  const illustrativeDownload = s.mode === "3D" && appearanceActive(scene, s);
  const downloadTarget = illustrativeDownload
    ? scene.asset?.files["appearance.glb"]
    : modelDownload || wholeModelDownload;
  const writable = ["surveyor", "admin"].includes(member.role);

  return (
    <aside className="inspector">
      <div className="flex items-center justify-between">
        <p className="eyebrow">{obj.kind} INFORMATION</p>
        <Badge>
          {text(
            status.isPending
              ? "Loading status…"
              : status.error
                ? "Status unavailable"
                : status.data?.result.accepted
                  ? "Accepted"
                  : status.data?.result.validated
                    ? "Validated"
                    : "Draft",
          )}
        </Badge>
      </div>
      <h2 className="mt-3">
        {obj.kind === "BUILDING" ? "Building " : ""}
        {obj.label.replace("Demo / Synthetic Dataset — ", "")}
      </h2>
      <p className="record-reference">
        {obj.kind === "BUILDING" ? "Parent ULPIN: " : "Record: "}
        {obj.kind === "BUILDING"
          ? scene.objects.find((o) => o.kind === "PARCEL")?.existing_ulpin ||
            "Not supplied"
          : obj.id.slice(0, 8)}
        <button
          aria-label="Copy record reference"
          onClick={() =>
            navigator.clipboard
              .writeText(
                obj.kind === "BUILDING"
                  ? scene.objects.find((o) => o.kind === "PARCEL")
                      ?.existing_ulpin || "Not supplied"
                  : obj.id.slice(0, 8),
              )
              .then(() => setMessage("Record reference copied"))
              .catch(() => setMessage("Clipboard unavailable"))
          }
        >
          <Copy size={14} />
        </button>
      </p>
      <div className="tabs">
        {["Overview", "Floors", "Units", "Validation"].map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Overview" ? (
        <>
          {g && (
            <>
              {obj.kind === "BUILDING" && (
                <div className="building-summary">
                  <AssetPreview
                    url={scene.asset?.files["appearance.png"]}
                    alt="Illustrative synthetic building exterior"
                  />
                  <dl>
                    <dt>Total floors</dt>
                    <dd>
                      {
                        scene.objects.filter(
                          (o) =>
                            floorIds.has(o.id) && o.semantic_type !== "ROOF",
                        ).length
                      }
                    </dd>
                    <dt>Total units</dt>
                    <dd>{units.length}</dd>
                    <dt>Building footprint</dt>
                    <dd>{g.area_m2.toFixed(0)} m²</dd>
                    <dt>
                      {g.height_estimated
                        ? "Estimated height"
                        : "Recorded height"}
                    </dt>
                    <dd>
                      {g.z_min !== null && g.z_max !== null
                        ? (g.z_max - g.z_min).toFixed(1) + " m"
                        : "Not supplied"}
                    </dd>
                  </dl>
                </div>
              )}
              <div
                className={
                  "detail-grid " +
                  (obj.kind === "BUILDING" ? "building-details-duplicate" : "")
                }
              >
                <div>
                  <small>Footprint</small>
                  <strong>{g.area_m2.toFixed(1)} m²</strong>
                </div>
                <div>
                  <small>
                    Height {g.height_estimated ? "· estimated" : ""}
                  </small>
                  <strong>
                    {g.z_min !== null && g.z_max !== null
                      ? (g.z_max - g.z_min).toFixed(1) + " m"
                      : "Not supplied"}
                  </strong>
                </div>
                {obj.kind === "BUILDING" && (
                  <>
                    <div>
                      <small>Total floors</small>
                      <strong>{floorIds.size}</strong>
                    </div>
                    <div>
                      <small>Property units</small>
                      <strong>{units.length}</strong>
                    </div>
                  </>
                )}
              </div>
              <details
                className="geometry-details"
                open={obj.kind !== "BUILDING"}
              >
                <summary>Source & geometry details</summary>
                <dl className="meta">
                  <dt>Proposed 3D ULPIN</dt>
                  <dd>
                    {scene.identities[g.id] || "Not issued for this geometry"}
                  </dd>
                  <dt>Source / boundary method</dt>
                  <dd>
                    {g.source_category.replaceAll("_", " ")} · {g.method}
                  </dd>
                  {g.confidence !== null && (
                    <>
                      <dt>Source / model confidence</dt>
                      <dd>
                        {(g.confidence * 100).toFixed(1)}% · not legal certainty
                      </dd>
                    </>
                  )}
                  <dt>Vertical extent</dt>
                  <dd>
                    {g.z_min !== null
                      ? g.z_min + " to " + g.z_max + " m"
                      : "Not supplied"}
                    <br />
                    {g.elevation_reference}
                  </dd>
                  <dt>Volume</dt>
                  <dd>
                    {g.volume_m3 !== null
                      ? g.volume_m3.toFixed(2) + " m³"
                      : "Not available"}
                  </dd>
                  <dt>Geometry version</dt>
                  <dd>
                    {g.version} · {new Date(g.created_at).toLocaleDateString()}
                  </dd>
                </dl>
              </details>
            </>
          )}
          <h3 className="section-title">Quick actions</h3>
          <div className="actions">
            {obj.kind === "BUILDING" && (
              <Button
                variant="outline"
                disabled={!writable || busy}
                onClick={() =>
                  action(async () => {
                    const identity = await api<{ identifier: string }>(
                      "/ulpin/" + obj.id,
                      {},
                    );
                    setMessage("Proposed 3D ULPIN: " + identity.identifier);
                  })
                }
              >
                Assign Proposed 3D ULPIN
              </Button>
            )}

            <Button variant="outline" onClick={() => setTab("Floors")}>
              View floors
            </Button>
            <Button variant="outline" onClick={() => setTab("Units")}>
              View units
            </Button>
            <Button
              variant="outline"
              disabled={!writable || busy || !g}
              onClick={() =>
                action(async () => {
                  const j = await api<RecordData>(
                    "/pipeline/validate/" + obj.id,
                    {},
                  );
                  setMessage(
                    "Validation queued · " +
                      j.id +
                      ". Processing updates appear in Home.",
                  );
                })
              }
            >
              Run validation
            </Button>
            <Button
              variant="outline"
              disabled={!downloadTarget || busy}
              title={
                downloadTarget
                  ? illustrativeDownload
                    ? "Download illustrative exterior and context; not cadastral geometry"
                    : "Download generated source model"
                  : "No generated model for the current geometry; regenerate parcel assets"
              }
              onClick={() =>
                action(() =>
                  download(
                    downloadTarget!,
                    (illustrativeDownload ? "illustrative-exterior-" : "") +
                      obj.id +
                      ".glb",
                  ),
                )
              }
            >
              <Download size={14} />
              Download 3D model
            </Button>
          </div>
          <h3 className="section-title">Recorded rights</h3>
          {rights.data?.length ? (
            rights.data.map((r) => (
              <div className="meta mt-3" key={text(r.id)}>
                <Badge>{text(r.right_type).replaceAll("_", " ")}</Badge>
                <p>{text(r.party_reference)}</p>
                <p>{text(r.description)}</p>
              </div>
            ))
          ) : (
            <p className="muted text-xs">No rights recorded</p>
          )}
          <h3 className="section-title">Evidence</h3>
          {evidence.data?.length ? (
            evidence.data.map((e) => (
              <button
                className="tree-item"
                key={text(e.id)}
                onClick={() =>
                  action(() =>
                    download(
                      "/api/v1/datasets/" + e.dataset_id + "/original",
                      text(e.dataset_id) + ".bin",
                    ),
                  )
                }
              >
                {text(e.description)}
                <br />
                <small>
                  {new Date(text(e.created_at)).toLocaleDateString()} · Download
                  source
                </small>
              </button>
            ))
          ) : (
            <p className="muted text-xs">No linked evidence</p>
          )}
          <h3 className="section-title">Property history</h3>
          {history.data?.items.length ? (
            history.data.items.map((h) => (
              <div className="meta mt-3" key={text(h.id)}>
                <strong>{text(h.operation)}</strong>
                <p>{text(h.reason)}</p>
                <small>{new Date(text(h.timestamp)).toLocaleString()}</small>
              </div>
            ))
          ) : (
            <p className="muted text-xs">No recorded changes</p>
          )}
        </>
      ) : tab === "Floors" ? (
        <>
          {(obj.kind === "FLOOR"
            ? [obj]
            : children.filter((o) => o.kind === "FLOOR")
          ).map((f) => (
            <button
              className="tree-item"
              key={f.id}
              onClick={() => s.set({ selected: f.id, floor: f.id })}
            >
              {f.label.replace("Demo / Synthetic Dataset — ", "")}
              <ChevronRight size={12} />
            </button>
          ))}
          {!children.some((o) => o.kind === "FLOOR") &&
            obj.kind !== "FLOOR" && <Empty />}
        </>
      ) : tab === "Units" ? (
        <>
          {units.map((u) => (
            <button
              className="tree-item"
              key={u.id}
              onClick={() => s.set({ selected: u.id, issue: null })}
            >
              {u.label.replace("Demo / Synthetic Dataset — ", "")}
              <br />
              <small>{u.id.slice(0, 8)}</small>
            </button>
          ))}
          {!units.length && <Empty />}
        </>
      ) : (
        <>
          {selectedIssue && (
            <div className="notice">
              <Badge severity={selectedIssue.severity}>
                {selectedIssue.severity}
              </Badge>
              <h3 className="mt-3">
                {selectedIssue.code.replaceAll("_", " ")}
              </h3>
              <p className="mt-2">{selectedIssue.message}</p>
              <dl className="meta">
                <dt>Affected</dt>
                <dd>{selectedIssue.object_label}</dd>
                <dt>Measured overlap</dt>
                <dd>
                  {text(
                    selectedIssue.details.intersection_volume_m3 ??
                      selectedIssue.details.volume_m3,
                  )}{" "}
                  m³
                </dd>
                <dt>Action</dt>
                <dd>
                  {text(
                    selectedIssue.details.action ||
                      "Review the boundary and source evidence",
                  )}
                </dd>
              </dl>
              <Button
                className="mt-3"
                variant="outline"
                onClick={() => setTab("Overview")}
              >
                Inspect boundary / evidence
              </Button>
            </div>
          )}
          {issues.data?.result.items
            .filter((i) => i.object_id === obj.id)
            .map((i) => (
              <button
                key={i.id}
                className="tree-item"
                onClick={() => s.set({ issue: i.id })}
              >
                <Badge severity={i.severity}>{i.severity}</Badge>
                <p className="mt-2">{i.code.replaceAll("_", " ")}</p>
                <small>{i.status}</small>
              </button>
            ))}
          {!issues.data?.result.items.some((i) => i.object_id === obj.id) && (
            <Empty />
          )}
        </>
      )}
      {message && (
        <p role="status" className="notice mt-4">
          {message}
        </p>
      )}
      <ErrorNotice error={rights.error || evidence.error || status.error} />
      <GovernancePanel key={obj.id} obj={obj} scene={scene} member={member} />
    </aside>
  );
}

function Reports() {
  const s = useWorkspace();
  const [report, setReport] = useState<RecordData | null>(null),
    [error, setError] = useState("");
  return (
    <section className="list-page">
      <div className="page-head">
        <div>
          <p className="eyebrow">RECORD EXPORTS</p>
          <h1>Reports</h1>
        </div>
      </div>
      <div className="card">
        <h2>Selected property snapshot</h2>
        <p className="muted mt-2">
          Select a property in Map to export its geometry, rights, evidence and
          history.
        </p>
        <Button
          className="mt-5"
          disabled={!s.selected}
          onClick={async () => {
            try {
              const response = await api<Envelope<RecordData>>(
                "/governance/objects/" + s.selected,
              );
              setReport(response.result);
              setError("");
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          Generate property report
        </Button>
        {report && (
          <>
            <Button
              className="ml-2"
              variant="outline"
              onClick={() => {
                const blob = new Blob([JSON.stringify(report, null, 2)], {
                  type: "application/json",
                });
                const u = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = u;
                a.download = "astra-property-report.json";
                a.click();
                URL.revokeObjectURL(u);
              }}
            >
              Download JSON
            </Button>
            <ReportView report={report} />
          </>
        )}
        <ErrorNotice error={error} />
      </div>
    </section>
  );
}

function SettingsPage({ member }: { member: Member }) {
  const s = useWorkspace();
  return (
    <section className="list-page">
      <h1>Settings</h1>
      <DemoDataSettings member={member} />
      {member.role === "admin" && <AdminMembers />}
      <div className="card mt-6 max-w-xl">
        <h2>Rendering preference</h2>
        <label>
          Performance mode
          <select
            value={s.performance}
            onChange={(e) =>
              s.set({
                performance: e.target.value as "Standard" | "Low-end",
                ...(e.target.value === "Low-end"
                  ? {
                      mode: "2D",
                      notice:
                        "Low-end mode selected. Showing the 2D cadastral view.",
                    }
                  : {}),
              })
            }
          >
            <option>Standard</option>
            <option>Low-end</option>
          </select>
        </label>
        <h3 className="section-title">Project access</h3>
        <dl className="meta">
          <dt>Role</dt>
          <dd>{member.role}</dd>
        </dl>
      </div>
    </section>
  );
}

function DemoDataSettings({ member }: { member: Member }) {
  const client = useQueryClient(),
    s = useWorkspace();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const data = useQuery({
    queryKey: ["demo-controls"],
    queryFn: () =>
      api<{
        available: boolean;
        synthetic_objects: number;
        operation: {
          status: string;
          error?: string;
          result?: { parcel_id: string };
        };
      }>("/demo"),
    retry: false,
    refetchInterval: 2000,
  });
  const operation = data.data?.operation;
  const previous = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (previous.current === "RUNNING" && operation?.status !== "RUNNING")
      void client.invalidateQueries();
    previous.current = operation?.status;
  }, [operation?.status, client]);
  if (!data.data?.available) return null;
  const run = async (remove: boolean) => {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ status: string }>(
        remove ? "/demo" : "/demo/seed",
        remove ? undefined : {},
        remove ? "DELETE" : "POST",
      );
      if (result.status === "FAILED")
        throw new Error(
          "Records removed; some source files could not be deleted. See the operation log.",
        );
      s.set({
        parcel: null,
        selected: null,
        floor: null,
        issue: null,
        appearance: true,
      });
      await client.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card mt-6 max-w-xl">
      <h2>Synthetic data</h2>
      <p className="muted mt-2">{data.data.synthetic_objects} records</p>
      <div className="case-actions">
        <Button
          disabled={
            busy || operation?.status === "RUNNING" || member.role === "viewer"
          }
          onClick={() => void run(false)}
        >
          Seed synthetic data
        </Button>
        <Button
          variant="outline"
          disabled={
            busy ||
            operation?.status === "RUNNING" ||
            member.role === "viewer" ||
            !data.data.synthetic_objects
          }
          onClick={() => {
            if (
              window.confirm(
                "Delete all synthetic records and their stored files? Login accounts and audit history will remain.",
              )
            )
              void run(true);
          }}
        >
          Delete all synthetic data
        </Button>
      </div>
      {operation?.status === "RUNNING" && (
        <p role="status">Generating building...</p>
      )}
      {operation?.status === "COMPLETED" && <p role="status">Completed</p>}
      {(error || operation?.status === "FAILED") && (
        <p role="alert" className="error">
          {error || operation?.error || "Operation failed"}
        </p>
      )}
    </div>
  );
}
