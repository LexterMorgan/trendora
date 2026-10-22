"use client";

import { useEffect, useRef, useState } from "react";

import type { ReferenceIdJson } from "@/lib/report-api";
import { askReport } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";

export interface AskPanelProps {
  reportId: string | null;
  onTrace: (answer: string, citations: ReferenceIdJson[]) => void;
}

export function AskPanel({ reportId, onTrace }: AskPanelProps) {
  const pending = useRef<AbortController | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    answer: string;
    citations: ReferenceIdJson[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopped, setStopped] = useState(false);

  useEffect(() => () => {
    pending.current?.abort();
    pending.current = null;
  }, [reportId]);

  function cancel() {
    pending.current?.abort();
    pending.current = null;
    setBusy(false);
    setStopped(true);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!reportId || busy || trimmed.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setStopped(false);
    const controller = new AbortController();
    pending.current = controller;
    try {
      const payload = await askReport(reportId, trimmed, { signal: controller.signal });
      if (pending.current !== controller) return;
      setResult({ answer: payload.answer, citations: payload.citations });
    } catch (err) {
      if (pending.current !== controller) return;
      if (err instanceof ResearchApiError && err.code === "ungrounded_answer") {
        setError("That answer could not be traced to this report's sources. Ask again.");
      } else if (err instanceof ResearchApiError) {
        setError(err.message);
      } else {
        setError("The answer could not be produced.");
      }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <section className="report-primary-section" aria-labelledby="ask-title">
      <h3 className="section-title" id="ask-title">
        Ask this report
      </h3>
      <p className="section-note">
        Answers use this report&apos;s findings and sources. Citations identify
        sources, not exact supporting passages; check them before relying on an answer.
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
          {busy && <button type="button" className="secondary-button" onClick={cancel}>Cancel</button>}
        </form>
      ) : (
        <p className="drawer-muted">Save this report first to ask about it.</p>
      )}
      <p className="drawer-muted" role="status">
        {busy ? "Looking for an answer in this report…" : stopped
          ? "Stopped waiting. The provider may still finish its request." : ""}
      </p>
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
