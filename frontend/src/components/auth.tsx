"use client";
import { createClient } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowUpRight,
  Eye,
  EyeOff,
  Layers3,
  Lock,
  Mail,
  ShieldCheck,
} from "lucide-react";
import { api, setToken } from "@/lib/api";
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
export const supabase = url && key ? createClient(url, key) : null;
export type Member = { id: string; role: string; active: boolean };
export function Auth({ onMember }: { onMember: (member: Member) => void }) {
  const [demo, setDemo] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [token, setAccess] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [showPassword, setShowPassword] = useState(false);
  useEffect(() => {
    if (!supabase)
      void api<{ enabled: boolean }>("/auth/demo-config")
        .then((v) => setDemo(v.enabled))
        .catch(() => setDemo(false));
  }, []);
  const connect = useCallback(
    async (value: string) => {
      setBusy(true);
      setError("");
      setToken(value);
      try {
        onMember(await api<Member>("/auth/me"));
      } catch (e) {
        setToken("");
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [onMember],
  );
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) void connect(data.session.access_token);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) setToken(session.access_token);
    });
    return () => data.subscription.unsubscribe();
  }, [connect]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (supabase) {
        const { data, error: authError } =
          await supabase.auth.signInWithPassword({ email, password });
        if (authError) throw authError;
        if (data.session) await connect(data.session.access_token);
      } else if (demo) {
        const session = await api<{ access_token: string }>(
          "/auth/demo-login",
          { email, password },
        );
        await connect(session.access_token);
      } else throw new Error("Sign-in service is unavailable.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-shell">
      <section className="auth-story" aria-label="About Astra 3D MAP">
        <div className="auth-brand">
          <Layers3 size={30} strokeWidth={1.5} />
          <span>ASTRA 3D MAP</span>
          <small>SPATIAL RECORDS</small>
        </div>
        <div className="auth-story-copy">
          <p className="eyebrow">VERTICAL PROPERTY MAPPING</p>
          <h1>
            Every space.
            <br />
            Clearly mapped.
          </h1>
          <p>Explore the building, floor and unit records in one workspace.</p>
        </div>
        <div className="parcel-art" aria-hidden="true">
          <div className="parcel-grid" />
          <div className="art-tower">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div className="art-floor" key={i} style={{ bottom: i * 29 }}>
                <span />
                <span />
                <span />
              </div>
            ))}
          </div>
          <span className="art-caption">PARCEL / BUILDING / FLOOR / UNIT</span>
        </div>
        <div className="auth-story-footer">
          <span>3D Property Mapping</span>
          <span>SIH26011 / 2026</span>
        </div>
      </section>
      <main className="auth-panel">
        <div className="auth-topline">
          <span>PROPERTY WORKSPACE</span>
          <ShieldCheck size={19} />
        </div>
        <div className="auth-form-wrap">
          <span className="auth-pill">
            {demo ? "Local demonstration" : "Member access"}
          </span>
          <h2>Welcome back.</h2>
          <p className="auth-intro">Sign in to Astra 3D MAP.</p>
          <form onSubmit={submit} className="auth-form">
            <label htmlFor="email">Email address</label>
            <div className="auth-input">
              <Mail size={18} />
              <input
                id="email"
                aria-label="Email"
                type="email"
                placeholder="you@organisation.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={!supabase && !demo}
                required
              />
            </div>
            <label htmlFor="password">Password</label>
            <div className="auth-input">
              <Lock size={18} />
              <input
                id="password"
                aria-label="Password"
                type={showPassword ? "text" : "password"}
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={!supabase && !demo}
                required
              />
              <button
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <button
              className="auth-submit"
              type="submit"
              disabled={(!supabase && !demo) || busy}
            >
              {busy ? "Signing in..." : "Sign in"}
              <ArrowUpRight size={19} />
            </button>
          </form>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <p className="auth-access-note">
            <ShieldCheck size={16} /> Your assigned role determines workspace
            access.
          </p>
          {demo && <p className="auth-demo-note">Demo / Synthetic Dataset</p>}
          <details className="auth-advanced">
            <summary>Use an existing access token</summary>
            <label htmlFor="jwt-token">JWT access token</label>
            <textarea
              id="jwt-token"
              aria-label="JWT access token"
              value={token}
              onChange={(e) => setAccess(e.target.value)}
              rows={3}
            />
            <button
              className="auth-submit"
              type="button"
              disabled={busy || !token}
              onClick={() => void connect(token)}
            >
              Connect session
            </button>
          </details>
        </div>
        <footer className="auth-footer">
          Proposed 3D ULPIN <span>ASTRA 3D MAP / 2026</span>
        </footer>
      </main>
    </div>
  );
}
