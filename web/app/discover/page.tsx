"use client";

import { useEffect, useRef, useState } from "react";
import { Protected } from "@/components/Protected";
import { AppShell } from "@/components/research/AppShell";
import { requestJson } from "@/lib/api";
import { ResearchApiError } from "@/lib/trendora-api";

interface DiscoverSourceJson {
  source_code: string;
  content_external_id: string;
  title: string;
  url: string;
  published_at: string | null;
  description: string;
}

interface DiscoverResponseJson {
  query: string;
  status: "ok" | "source_unavailable";
  sources: DiscoverSourceJson[];
}

type Phase = "idle" | "loading" | "done" | "error" | "cancelled";

export default function DiscoverPage() {
  return (
    <Protected>
      <Discover />
    </Protected>
  );
}

function Discover() {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<DiscoverResponseJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pending = useRef<AbortController | null>(null);
  const requestId = useRef(0);

  useEffect(() => () => {
    requestId.current += 1;
    pending.current?.abort();
    pending.current = null;
  }, []);

  function cancel() {
    const controller = pending.current;
    if (!controller) return;
    requestId.current += 1;
    pending.current = null;
    controller.abort();
    setResult(null);
    setError(null);
    setPhase("cancelled");
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || phase === "loading") return;
    const id = ++requestId.current;
    const controller = new AbortController();
    pending.current?.abort();
    pending.current = controller;
    setPhase("loading");
    setError(null);
    setResult(null);
    try {
      const params = new URLSearchParams({ q: trimmed, limit: "10" });
      const payload = await requestJson<DiscoverResponseJson>(
        `/api/discover?${params.toString()}`,
        { signal: controller.signal },
      );
      if (id !== requestId.current || pending.current !== controller) return;
      setResult(payload);
      setPhase("done");
    } catch (err) {
      if (
        id !== requestId.current ||
        controller.signal.aborted ||
        (err instanceof Error && err.name === "AbortError")
      ) return;
      const message = err instanceof ResearchApiError
        ? err.code === "discover_timeout"
          ? "Search took too long. Try a narrower query."
          : err.kind === "network"
            ? "The search service could not be reached. Try again."
            : err.message
        : "The search could not be completed.";
      setError(message);
      setPhase("error");
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }

  const statusText =
    phase === "idle"
      ? "Enter a topic to search the public web."
      : phase === "loading"
        ? "Searching the public web…"
        : phase === "error"
          ? "Search failed."
          : phase === "cancelled"
            ? "Stopped waiting. The search service may still finish. You can edit the query and search again."
            : result?.status === "source_unavailable"
            ? "Public web search is unavailable right now."
            : result && result.sources.length === 0
              ? "No results."
              : `${result?.sources.length ?? 0} ${
                  result?.sources.length === 1 ? "result" : "results"
                }.`;

  return (
    <AppShell view="discover" section="Explore sources">
      <div className="discover-page research-page">
        <section className="page-heading">
        <div>
          <h1>Explore sources</h1>
          <p>
            Search indexed titles and snippets from the public web. This page
            does not generate an AI report.
          </p>
        </div>
      </section>

      <form className="discover-form" onSubmit={handleSubmit}>
        <div className="form-field discover-query">
          <label htmlFor="discover-query">Search the public web</label>
          <input
            ref={inputRef}
            id="discover-query"
            type="search"
            value={query}
            maxLength={200}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search the public web"
            placeholder="Topic or keyword"
            disabled={phase === "loading"}
          />
        </div>
        <button
          type="submit"
          className="primary-button"
          disabled={phase === "loading" || query.trim().length === 0}
        >
          {phase === "loading" ? "Searching…" : "Search"}
        </button>
        {phase === "loading" && (
          <button
            type="button"
            className="secondary-button"
            onClick={cancel}
          >
            Cancel search
          </button>
        )}
      </form>

      <p className="loading-note discover-status" role="status">
        {statusText}
      </p>
      {error && (
        <p className="form-error discover-status" role="alert">
          {error}
        </p>
      )}

      {result?.status === "ok" && result.sources.length > 0 && (
        <ul className="discover-results" aria-label="Public web results">
          {result.sources.map((source) => (
            <li
              key={`${source.source_code}:${source.content_external_id}`}
              className="discover-result"
            >
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {source.title || source.url}
              </a>
              {source.description && <p>{source.description}</p>}
            </li>
          ))}
        </ul>
      )}
      </div>
    </AppShell>
  );
}
