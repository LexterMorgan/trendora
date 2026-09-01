"use client";

import { useState } from "react";

import { ResearchForm, type ResearchFormValues } from "@/components/ResearchForm";
import { CoveragePanel } from "@/components/CoveragePanel";
import { ReferenceList } from "@/components/ReferenceList";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MarketCaveat } from "@/components/MarketCaveat";
import {
  submitResearch,
  type ResearchResponse,
  ResearchApiError,
} from "@/lib/trendora-api";
import { sourceLabel } from "@/lib/format";

interface DisplayError {
  code: string;
  message: string;
}

export default function Home() {
  const [result, setResult] = useState<ResearchResponse | null>(null);
  const [error, setError] = useState<DisplayError | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(values: ResearchFormValues) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await submitResearch(values);
      setResult(response);
    } catch (err) {
      if (err instanceof ResearchApiError) {
        setError({ code: err.code, message: err.message });
      } else {
        setError({ code: "internal_error", message: "An unexpected error occurred." });
      }
    } finally {
      setLoading(false);
    }
  }

  const referenceCount = result?.references.length ?? 0;

  return (
    <main className="workspace">
      <header className="masthead">
        <p className="brand">TRENDORA</p>
        <h1 className="tagline">Social Content Intelligence</h1>
        <p className="subtitle">
          Research real content before deciding what to post.
        </p>
      </header>

      <div className="research-layout">
        <section className="panel form-panel" aria-label="Research request">
          <h2 className="section-title">Research</h2>
          <ResearchForm onSubmit={handleSubmit} disabled={loading} />
        </section>

        <section className="results" aria-live="polite">
          {loading && (
            <div className="loading-note" role="status">
              Researching YouTube…
            </div>
          )}

          {error && <ErrorState code={error.code} message={error.message} />}

          {result && !loading && (
            <>
              <div className="result-header">
                <h2 className="section-title">Research complete</h2>
                <p className="result-summary">
                  {referenceCount}{" "}
                  {referenceCount === 1 ? "reference" : "references"} · executed:{" "}
                  {result.executed_sources.map(sourceLabel).join(", ") || "none"}
                </p>
              </div>
              <MarketCaveat market={result.query.market} />
              <CoveragePanel
                coverage={result.coverage}
                executedSources={result.executed_sources}
              />
              {referenceCount > 0 ? (
                <ReferenceList references={result.references} />
              ) : (
                <EmptyState />
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
