"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import TrendsTable, { type TrendsPayload } from "@/components/trends-table";
import { ApiError, fetchTrends } from "@/lib/api";
import { syntheticTrends } from "@/lib/synthetic";

type Mode =
  | { state: "form" }
  | { state: "connecting" }
  | { state: "connected"; payload: TrendsPayload; live: true }
  | { state: "demo"; payload: TrendsPayload }
  | { state: "failed"; message: string };

const STORE_KEY = "anviq.dashboard.v1";

type Saved = { apiBase: string; token: string };

function readSaved(): Saved {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORE_KEY) ?? "{}");
    if (typeof parsed === "object" && parsed !== null) {
      const { apiBase, token } = parsed as Record<string, unknown>;
      if (typeof apiBase === "string" && typeof token === "string") {
        return { apiBase, token };
      }
    }
  } catch {
    /* a corrupt entry is treated as empty */
  }
  return { apiBase: "", token: "" };
}

export default function Home() {
  const [mode, setMode] = useState<Mode>({ state: "form" });
  const [apiBase, setApiBase] = useState("");
  const [token, setToken] = useState("");
  const [remember, setRemember] = useState(true);

  const failure = useCallback((error: unknown) => {
    if (error instanceof ApiError) return error.message;
    return "Something unexpected went wrong.";
  }, []);

  useEffect(() => {
    const saved = readSaved();
    setApiBase(saved.apiBase);
    setToken(saved.token);
    let cancelled = false;
    if (saved.apiBase && saved.token) {
      setMode({ state: "connecting" });
      fetchTrends(saved.apiBase, saved.token)
        .then((payload) => {
          if (!cancelled) setMode({ state: "connected", payload, live: true });
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setMode({ state: "failed", message: failure(error) });
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, []);

  const connect = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      setMode({ state: "connecting" });
      if (remember) {
        window.localStorage.setItem(STORE_KEY, JSON.stringify({ apiBase, token }));
      } else {
        window.localStorage.removeItem(STORE_KEY);
      }
      try {
        const payload = await fetchTrends(apiBase, token);
        setMode({ state: "connected", payload, live: true });
      } catch (error) {
        setMode({ state: "failed", message: failure(error) });
      }
    },
    [apiBase, token, remember, failure],
  );

  const signOut = useCallback(() => {
    window.localStorage.removeItem(STORE_KEY);
    setToken("");
    setApiBase("");
    setMode({ state: "form" });
  }, []);

  return (
    <main>
      <header className="head">
        <h1>Anviq mentor dashboard</h1>
        <p>
          Anonymous group trends only. <strong>Nothing about one teacher exists here</strong> —
          the server drops every group smaller than 20 teachers before the network layer, and
          there is no per-teacher view anywhere in the codebase.
        </p>
      </header>

      {mode.state === "connected" && (
        <>
          <TrendsTable payload={{ ...mode.payload }} />
          <button type="button" className="link" onClick={signOut}>
            forget connection on this device
          </button>
        </>
      )}

      {mode.state === "demo" && (
        <>
          <p className="badge demo">Demo data · synthetic · not from any deployment</p>
          <TrendsTable payload={{ ...mode.payload }} />
          <button type="button" className="link" onClick={() => setMode({ state: "form" })}>
            connect to a real feed instead
          </button>
        </>
      )}

      {mode.state === "failed" && (
        <p className="badge error" role="alert">
          {mode.message} <button type="button" className="link" onClick={() => setMode({ state: "form" })}>try again</button>
        </p>
      )}

      {mode.state === "connecting" && <p className="muted">connecting…</p>}

      {mode.state === "form" && (
        <form className="connect card" onSubmit={connect}>
          <h2>Connect to the trends feed</h2>
          <p className="muted">
            The URL of the Anviq API and the dashboard token distributed at the workshop. The
            token only stops scraping; anonymity is enforced by the k ≥ 20 view in the database.
          </p>
          <label>
            API URL
            <input
              value={apiBase}
              onChange={(event) => setApiBase(event.target.value)}
              placeholder="https://anviq-demo.duckdns.org"
              autoComplete="url"
            />
          </label>
          <label>
            Dashboard token
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="a long random string from the team"
              autoComplete="off"
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
            />
            remember on this device (the device owner could connect without retyping)
          </label>
          <div className="actions">
            <button type="submit">show trends</button>
            <button
              type="button"
              className="secondary"
              onClick={() => setMode({ state: "demo", payload: syntheticTrends() })}
            >
              look at demo data
            </button>
          </div>
        </form>
      )}

      <footer className="foot">
        Built for judges: groups smaller than 20 are suppressed server-side, by a
        <code>public_trends</code> database view the dashboard role can read and nothing more.
      </footer>
    </main>
  );
}
