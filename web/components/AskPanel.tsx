"use client";

import { useState } from "react";

import type { CitationJson } from "@/lib/report-api";
import { askReport } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";

export interface AskPanelProps {
  reportId: string | null;
  onTrace: (answer: string, citations: CitationJson[]) => void;
}

/**
 * One question against a saved report. The backend refuses any answer that
 * cannot be cited back to this report, so there is no "unsourced answer"
 * state to render here.
 */
export function AskPanel({ reportId, onTrace }: AskPanelProps) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    answer: string;
    citations: CitationJson[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!reportId || busy || trimmed.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload = await askReport(reportId, trimmed);
      setResult({ answer: payload.answer, citations: payload.citations });
    } catch (err) {
      if (err instanceof ResearchApiError && err.code === "ungrounded_answer") {
        setError("That answer could not be traced to this report's sources. Ask again.");
      } else if (err instanceof ResearchApiError) {
        setError(err.message);
      } else {
        setError("The answer could not be produced.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="report-primary-section" aria-labelledby="ask-title">
      <h3 className="section-title" id="ask-title">
        Ask this report
      </h3>
      <p className="section-note">
        Answers use only this report&apos;s findings and sources. An answer that
        cannot be traced back to them is refused.
      </p>
      {reportId ? (
        <form className="ask-form" onSubmit={handleSubmit}>
          <input
            className="ask-input"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={500}
            placeholder="What changed in this topic?"
            aria-label="Question about this report"
            disabled={busy}
          />
          <button
            type="submit"
            className="secondary-button"
            disabled={busy || question.trim().length === 0}
          >
            {busy ? "Asking…" : "Ask"}
          </button>
        </form>
      ) : (
        <p className="drawer-muted">Save this report first to ask about it.</p>
      )}
      {error && (
        <p className="drawer-muted" role="alert">
          {error}
        </p>
      )}
      {result && (
        <div className="report-item">
          <p className="report-statement">{result.answer}</p>
          <button
            type="button"
            className="citation-toggle"
            onClick={() => onTrace(result.answer, result.citations)}
          >
            Trace {result.citations.length}{" "}
            {result.citations.length === 1 ? "citation" : "citations"}
          </button>
        </div>
      )}
    </section>
  );
}
