"use client";

import { useEffect, useRef, useState } from "react";

import { getSessionStore } from "@/lib/auth/client";
import { saveReportSnapshot, type ResearchReportResponse } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/api";
import { createSubmitGate } from "@/lib/submit-gate";
import {
  isTerminalSaveCode,
  newRequestId,
  REQUEST_ID_ERROR_MESSAGE,
  saveStatusForErrorCode,
  saveStatusFromOutcome,
  terminalSaveMessage,
  type SaveAttempt,
} from "@/lib/report-planner-actions";

interface ReportPersistencePanelProps {
  report: ResearchReportResponse;
  onResolved?: (reportId: string) => void;
}

function provenanceLabel(origin: string | null): string | null {
  if (origin === "client_supplied") {
    return "Saved from this browser. Classified as client-supplied, not server-generated.";
  }
  if (origin === "legacy_unclassified") {
    return "This older report predates provenance tracking.";
  }
  return null;
}

/**
 * Generation vs persistence, shown as separate states.
 *
 * The report is rendered by the parent; this panel reports and retries the
 * save. The request key and snapshot are frozen on the first attempt so a
 * retry can never create a second report. On a confirmed save the canonical id
 * is published upward so import buttons enable without a reload.
 */
export function ReportPersistencePanel({ report, onResolved }: ReportPersistencePanelProps) {
  const initial = report.persistence ?? null;
  const [attempt, setAttempt] = useState<SaveAttempt | null>(
    initial
      ? {
          requestId: initial.request_id,
          reportId: initial.report_id,
          status: saveStatusFromOutcome(initial),
          errorCode: initial.error_code,
          origin: initial.snapshot_origin,
          recoveryReceipt: initial.recovery_receipt ?? null,
        }
      : null,
  );
  const [requestIdError, setRequestIdError] = useState<string | null>(null);
  const [gate] = useState(createSubmitGate);
  const publishedId = useRef<string | null>(null);
  const label = provenanceLabel(attempt?.origin ?? initial?.snapshot_origin ?? null);

  // Publish an already-confirmed generation outcome once, without a click.
  useEffect(() => {
    const id = initial?.report_id ?? null;
    if (initial?.status === "saved" && id && publishedId.current !== id) {
      publishedId.current = id;
      onResolved?.(id);
    }
  }, [initial?.report_id, initial?.status, onResolved]);

  async function save() {
    if (!gate.acquire()) return;
    let frozen: (SaveAttempt & { requestId: string }) | null = null;
    const session = getSessionStore();
    const binding = session.getSessionBinding();
    setRequestIdError(null);
    try {
      const requestId = attempt?.requestId ?? newRequestId();
      frozen = {
        ...(attempt ?? {
          reportId: null,
          status: "idle",
          errorCode: null,
          origin: "client_supplied",
          recoveryReceipt: initial?.recovery_receipt ?? null,
        }),
        requestId,
      };
      setAttempt({ ...frozen, status: "saving", errorCode: null });
      const result = await saveReportSnapshot(frozen.requestId, report, { recoveryReceipt: frozen.recoveryReceipt });
      const now = session.getSessionBinding();
      if (now.userId !== binding.userId || now.epoch !== binding.epoch) return;
      const reportId = result.persistence.report_id;
      setAttempt({
        ...frozen,
        status: "saved",
        reportId,
        origin: result.persistence.snapshot_origin,
        errorCode: null,
      });
      if (reportId) {
        publishedId.current = reportId;
        onResolved?.(reportId);
      }
    } catch (err) {
      const now = session.getSessionBinding();
      if (now.userId !== binding.userId || now.epoch !== binding.epoch) return;
      if (!frozen) {
        setRequestIdError(REQUEST_ID_ERROR_MESSAGE);
        return;
      }
      const code = err instanceof ResearchApiError ? err.code : "unknown_error";
      setAttempt({ ...frozen, status: saveStatusForErrorCode(code), errorCode: code });
    } finally {
      gate.release();
    }
  }

  const status = attempt?.status ?? "idle";
  const errorCode = attempt?.errorCode ?? null;
  const isTerminal = isTerminalSaveCode(errorCode);

  return (
    <div className="report-persistence" role="status" aria-live="polite">
      {requestIdError && <span className="persistence-failed">{requestIdError}</span>}
      {status === "idle" && <span className="drawer-muted">Not saved yet.</span>}
      {status === "saving" && <span className="drawer-muted">Saving report…</span>}
      {status === "saved" && <span className="persistence-saved">Saved to history.</span>}
      {status === "uncertain" && (
        <span className="persistence-uncertain">
          Save outcome is uncertain. Retry with the same key to confirm.
        </span>
      )}
      {status === "failed" && (
        <span className={isTerminal ? "persistence-too-large" : "persistence-failed"}>
          {isTerminal ? terminalSaveMessage(errorCode) : "This report was not saved."}
        </span>
      )}

      {status !== "saved" && !isTerminal && (
        <button type="button" className="secondary-button" onClick={save} disabled={status === "saving"}>
          {status === "idle" || status === "failed" ? "Save report" : "Retry saving report"}
        </button>
      )}

      {label && <p className="drawer-muted persistence-label">{label}</p>}
    </div>
  );
}
