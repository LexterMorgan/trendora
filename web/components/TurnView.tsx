"use client";

import type { ResearchFormValues } from "@/components/ResearchForm";
import type { ResearchReportResponse } from "@/lib/report-api";
import { ErrorState } from "@/components/ErrorState";
import { ReportView } from "@/components/ReportView";
import { sourceLabel } from "@/lib/format";

export interface SessionTurn {
  id: number;
  request: ResearchFormValues;
  userMessage: string;
  state: "loading" | "success" | "error";
  report: ResearchReportResponse | null;
  error: { code: string; message: string } | null;
}

interface TurnViewProps {
  turn: SessionTurn;
  onEdit: (request: ResearchFormValues) => void;
}

export function userMessage(request: ResearchFormValues): string {
  return [
    request.topic,
    request.market,
    `${request.date_from} → ${request.date_to}`,
    `${request.result_limit} results`,
    request.sources.map(sourceLabel).join(", "),
  ]
    .filter(Boolean)
    .join(" · ");
}

export function TurnView({ turn, onEdit }: TurnViewProps) {
  return (
    <article className="turn">
      <div className="turn-user">
        <span className="turn-label">You</span>
        <p className="turn-message">{turn.userMessage}</p>
        <button
          type="button"
          className="secondary-button"
          onClick={() => onEdit(turn.request)}
        >
          Edit and rerun
        </button>
      </div>

      <div className="turn-assistant">
        <span className="turn-label">Trendora</span>
        {turn.state === "loading" && (
          <p className="loading-note" role="status">
            Researching and generating report…
          </p>
        )}
        {turn.state === "error" && turn.error && (
          <ErrorState code={turn.error.code} message={turn.error.message} />
        )}
        {turn.state === "success" && turn.report && <ReportView report={turn.report} />}
      </div>
    </article>
  );
}
