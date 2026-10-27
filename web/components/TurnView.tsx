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
  state: "loading" | "success" | "error" | "cancelled";
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
  onCancel: () => void;
  onReportSaved?: (turnId: number) => void;
  onReportUpdated?: (turnId: number, report: ResearchReportResponse) => void;
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

/**
 * Content tools are opt-in. Report their requested and actual state separately:
 * a checked box never implies that ideas or briefs were generated.
 */
function contentToolsSummary(
  request: ResearchFormValues,
  state: SessionTurn["state"],
  report: ResearchReportResponse | null,
): string {
  if (!request.include_content_tools) return "Research only";
  if (state === "loading") return "Content ideas and briefs requested";
  if (state === "error") return "Content ideas and briefs requested; research failed";
  if (state === "cancelled") return "Content ideas and briefs requested; research cancelled";
  if (!report) return "Content ideas and briefs requested";
  const ideas = report.ideation?.content_ideas?.length ?? 0;
  const briefs = report.ideation?.content_briefs?.length ?? 0;
  if (ideas > 0 || briefs > 0) {
    const ideaLabel = `${ideas} ${ideas === 1 ? "idea" : "ideas"}`;
    const briefLabel = `${briefs} ${briefs === 1 ? "brief" : "briefs"}`;
    if (ideas > 0 && briefs > 0) {
      return `Content generated: ${ideaLabel}, ${briefLabel}`;
    }
    if (ideas > 0) return `Content generated: ${ideaLabel}; no briefs`;
    return `Content generated: ${briefLabel}; no ideas`;
  }
  if (report.status === "content_unavailable") {
    return "Content ideas and briefs requested; unavailable";
  }
  if (report.status === "no_evidence") {
    return "Content ideas and briefs not generated: no evidence";
  }
  if (report.status === "insufficient_evidence") {
    return "Content ideas and briefs not generated: insufficient evidence";
  }
  if (report.status === "research_unavailable") {
    return "Content ideas and briefs not generated: research unavailable";
  }
  return "Content ideas and briefs requested; none generated";
}

/** One quiet line of request detail under the topic. */
function requestMeta(
  request: ResearchFormValues,
  state: SessionTurn["state"],
  report: ResearchReportResponse | null,
): string {
  const scope = request.markets.length ? request.markets.join(", ") : "Global";
  return [
    scope,
    requestWindowLabel(request),
    // A request limit is not a result count.
    `up to ${request.result_limit} references`,
    request.sources.map(sourceLabel).join(", "),
    contentToolsSummary(request, state, report),
  ].join(" · ");
}

export function TurnView({ turn, onEdit, onRetry, onCancel, onReportSaved, onReportUpdated }: TurnViewProps) {
  return (
    <article className="turn">
      <div className="turn-user">
        <span className="turn-label">You</span>
        <p className="turn-message">{turn.request.topic}</p>
        <span className="turn-meta">{requestMeta(turn.request, turn.state, turn.report)}</span>
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
              Research is running for {turn.request.topic} (
              {requestWindowLabel(turn.request)}). Findings appear here when the run
              finishes.
            </p>
            <ElapsedTimer startedAt={turn.startedAt} />
            <div className="turn-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={onCancel}
              >
                Cancel research
              </button>
            </div>
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
        {turn.state === "cancelled" && (
          <p className="loading-note" role="status">
            Stopped waiting. The run may continue, and a saved report may still
            appear in Reports.
          </p>
        )}
        {turn.state === "success" && turn.report && (
          <ReportView
            key={turn.id}
            report={turn.report}
            clientElapsedMs={turn.clientElapsedMs}
            onSaved={() => onReportSaved?.(turn.id)}
            onReportUpdated={(report) => onReportUpdated?.(turn.id, report)}
          />
        )}
      </div>
    </article>
  );
}
