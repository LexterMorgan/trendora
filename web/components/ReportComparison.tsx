"use client";

import { useEffect, useState } from "react";
import { previousReportChanges, type PreviousReportChangesJson } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";
import { formatDate } from "@/lib/format";

export function ReportComparison({ reportId }: { reportId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<PreviousReportChangesJson | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    previousReportChanges(reportId, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setResult(data); })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof ResearchApiError
          ? err.message : "The previous report could not be compared.");
      });
    return () => controller.abort();
  }, [reportId, attempt]);

  if (error) return (
    <div className="report-brief-note">
      <p role="alert">Comparison unavailable: {error}</p>
      <button type="button" className="secondary-button" onClick={() => {
        setError(null);
        setResult(null);
        setAttempt((value) => value + 1);
      }}>Retry comparison</button>
    </div>
  );
  return <p className="report-brief-note" role="status">
    {!result ? "Comparing with the previous report…" : !result.previous_report_id
      ? "No earlier report with this exact topic is available."
      : `${result.new_findings.length} added, ${result.dropped_findings.length} removed finding statements since ${formatDate(result.previous_created_at)}. This compares wording, not real-world change.`}
  </p>;
}
