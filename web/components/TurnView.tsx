"use client";

import { useEffect, useState } from "react";

import { type ResearchFormValues } from "@/components/ResearchForm";
import type { ResearchReportResponse } from "@/lib/report-api";
import { ErrorState } from "@/components/ErrorState";
import { ReportView } from "@/components/ReportView";
import { formatElapsed } from "@/lib/elapsed";
import { sourceLabel } from "@/lib/format";

export interface SessionTurn {
  id: number;
  request: ResearchFormValues;
  state: "loading" | "success" | "error";
  report: ResearchReportResponse | null;
  error: { code: string; message: string; kind?: string } | null;
  /** Client clock at submit; the loading timer measures from here. */
  startedAt: number;
  /** Actual submit-to-response wait, set once the response arrives. */
  clientElapsedMs?: number;
}

interface TurnViewProps {
  turn: SessionTurn;
  onEdit: (request: ResearchFormValues) => void;
  onRetry: (request: ResearchFormValues) => void;
}

/** The window the request asked for, in plain words. */
function requestWindowLabel(request: ResearchFormValues): string {
  return request.date_from && request.date_to
    ? `${request.date_from} to ${request.date_to}`
    : "Last 30 days";
}

/** Actual browser wait, not simulated progress. Cleared on unmount. */
function ElapsedTimer({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  return (
    <p className="elapsed-note" role="timer" aria-live="off">
      Elapsed: {formatElapsed(now - startedAt)}. Stages are not estimated;
      measured run details appear when the response arrives.
    </p>
  );
}

/** One quiet line of request detail under the topic. */
function requestMeta(request: ResearchFormValues): string {
  const scope = request.markets.length ? request.markets.join(", ") : "Global";
  return [
    scope,
    requestWindowLabel(request),
    // A request limit is not a result count.
    `up to ${request.result_limit} references`,
    request.sources.map(sourceLabel).join(", "),
    request.include_content_tools ? "Content ideas and briefs included" : "Research only",
  ].join(" · ");
}

export function TurnView({ turn, onEdit, onRetry }: TurnViewProps) {
  return (
    <article className="turn">
      <div className="turn-user">
        <span className="turn-label">You</span>
        <p className="turn-message">{turn.request.topic}</p>
        <span className="turn-meta">{requestMeta(turn.request)}</span>
        <button
          type="button"
          className="turn-edit"
          onClick={() => onEdit(turn.request)}
        >
          Edit and rerun
        </button>
      </div>

      <div className="turn-assistant">
        <span className="turn-label">Trendora</span>
        {turn.state === "loading" && (
          <>
            <p className="loading-note" role="status">
              Searching {turn.request.sources.map(sourceLabel).join(" and ")} for{" "}
              {turn.request.topic} ({requestWindowLabel(turn.request)}). Findings appear here
              when the run finishes.
            </p>
            <ElapsedTimer startedAt={turn.startedAt} />
          </>
        )}
        {turn.state === "error" && turn.error && (
          <>
            <ErrorState code={turn.error.code} message={turn.error.message} />
            {(turn.error.kind === "unavailable" || turn.error.kind === "network") && (
              <div className="error-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onRetry(turn.request)}
                >
                  Retry
                </button>
              </div>
            )}
          </>
        )}
        {turn.state === "success" && turn.report && (
          <ReportView
            key={turn.id}
            report={turn.report}
            clientElapsedMs={turn.clientElapsedMs}
          />
        )}
      </div>
    </article>
  );
}
