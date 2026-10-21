"use client";

import { useState } from "react";

import { Header } from "@/components/Header";
import { Protected } from "@/components/Protected";
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

type Phase = "idle" | "loading" | "done" | "error";

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

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || phase === "loading") return;
    setPhase("loading");
    setError(null);
    setResult(null);
    try {
      const params = new URLSearchParams({ q: trimmed, limit: "10" });
      const payload = await requestJson<DiscoverResponseJson>(
        `/api/discover?${params.toString()}`,
      );
      setResult(payload);
      setPhase("done");
    } catch (err) {
      setError(
        err instanceof ResearchApiError
          ? err.message
          : "The search could not be completed.",
      );
      setPhase("error");
    }
  }

  const statusText =
    phase === "idle"
      ? "Enter a topic to search the public web."
      : phase === "loading"
        ? "Searching the public web…"
        : phase === "error"
          ? "Search failed."
          : result?.status === "source_unavailable"
            ? "Public web search is unavailable right now."
            : result && result.sources.length === 0
              ? "No results."
              : `${result?.sources.length ?? 0} ${
                  result?.sources.length === 1 ? "result" : "results"
                }.`;

  return (
    <main className="workspace">
      <Header section="Discover" />
      <section className="page-heading">
        <div>
          <h1>Discover</h1>
          <p>Search indexed public-web results for a topic.</p>
        </div>
      </section>

      <form className="discover-form" onSubmit={handleSubmit}>
        <div className="form-field discover-query">
          <label htmlFor="discover-query">Search the public web</label>
          <input
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
      </form>

      <p className="loading-note" role="status">
        {statusText}
      </p>
      {error && (
        <p className="form-error" role="alert">
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
    </main>
  );
}
