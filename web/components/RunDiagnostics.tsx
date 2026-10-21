"use client";

import type { ResearchReportResponse, RunDetailsJson } from "@/lib/report-api";
import { formatElapsed } from "@/lib/elapsed";

interface RunDiagnosticsProps {
  report: ResearchReportResponse;
  /** Actual submit-to-response wait measured in this browser, fresh runs only. */
  clientElapsedMs?: number | null;
}

const STAGE_LABELS: Record<string, string> = {
  collection: "Source collection",
  interpretation: "Interpretation",
  strategy: "Content gaps and opportunities",
  ideation: "Content ideas and briefs",
  persistence: "Saving",
};

const MODE_LABELS: Record<string, string> = {
  ai_interpretation: "AI interpretation",
  source_excerpts: "Source excerpts (extractive)",
  none: "No findings stage",
};

function usageLabel(
  prompt: number | null,
  completion: number | null,
  total: number | null,
): string {
  if (prompt === null && completion === null && total === null) {
    return "Provider token usage not returned";
  }
  const part = (name: string, value: number | null) =>
    `${name} ${value === null ? "not returned" : value.toLocaleString()}`;
  return `Provider-reported tokens: ${part("prompt", prompt)}, ${part("completion", completion)}, ${part("total", total)}`;
}

function StageList({ details }: { details: RunDetailsJson }) {
  const stages = Object.entries(details.stage_durations_ms);
  if (stages.length === 0) {
    return <p className="drawer-muted">No stage timings were recorded.</p>;
  }
  return (
    <dl className="run-stage-list">
      {stages.map(([stage, duration]) => (
        <div key={stage} className="run-stage">
          <dt>{STAGE_LABELS[stage] ?? stage}</dt>
          <dd>{formatElapsed(duration)}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Fresh-response measurements, kept outside the immutable snapshot. Saved and
 * legacy reports say the measurements were not recorded rather than showing
 * invented zeroes.
 */
export function RunDiagnostics({ report, clientElapsedMs }: RunDiagnosticsProps) {
  const details = report.run_details;
  if (!details) {
    return (
      <section className="report-section run-diagnostics" aria-label="Run details">
        <h3 className="section-title">Run details</h3>
        <p className="section-note">
          Run diagnostics unavailable for this report. Measurements were not
          recorded when it was saved.
        </p>
        <p className="drawer-muted">
          Missing diagnostics do not imply zero elapsed time, zero retries, or
          zero AI requests.
        </p>
      </section>
    );
  }

  return (
    <details className="report-section report-secondary-details run-diagnostics">
      <summary>Run details</summary>
      <p className="section-note">
        Measurements from this response only. They stay outside the saved
        report snapshot and its fingerprint.
      </p>

      <dl className="run-stage-list">
        <div className="run-stage">
          <dt>Backend run</dt>
          <dd>{formatElapsed(details.elapsed_ms)}</dd>
        </div>
        {clientElapsedMs != null && (
          <div className="run-stage">
            <dt>Browser wait (submit to response)</dt>
            <dd>{formatElapsed(clientElapsedMs)}</dd>
          </div>
        )}
      </dl>

      <h4 className="drawer-subheading">Measured stages</h4>
      <StageList details={details} />
      <p className="drawer-muted">
        A stage that did not run is absent, not zero.
      </p>

      <h4 className="drawer-subheading">Findings and attempts</h4>
      <p className="report-statement">
        Findings mode: {MODE_LABELS[details.finding_mode] ?? details.finding_mode}.
        Malformed-output retries: {details.retry_count}.
      </p>
      {details.ai_requests.length === 0 ? (
        <p className="drawer-muted">No AI provider request was recorded for this run.</p>
      ) : (
        <ol className="run-attempts">
          {details.ai_requests.map((request, index) => (
            <li key={index} className="run-attempt">
              <span className="chain-label">
                Attempt {index + 1} · {STAGE_LABELS[request.stage] ?? request.stage}
              </span>
              <span>
                {formatElapsed(request.elapsed_ms)} request time ·{" "}
                {request.request_bytes.toLocaleString()} serialized request bytes
              </span>
              <span className="drawer-muted">
                {usageLabel(request.prompt_tokens, request.completion_tokens, request.total_tokens)}
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className="drawer-muted">
        Serialized request bytes are not tokens or billing. Provider token
        subtotals are shown as returned and may not add up. Missing usage is
        unknown, not zero. Local cancellation stops this browser request; it
        does not guarantee the router or provider stopped its own work.
      </p>
    </details>
  );
}
