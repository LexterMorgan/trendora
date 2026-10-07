"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { getSessionStore } from "@/lib/auth/client";
import { importPlannerPost } from "@/lib/planner-api";
import { ResearchApiError } from "@/lib/api";
import { createSubmitGate } from "@/lib/submit-gate";
import { newRequestId, REQUEST_ID_ERROR_MESSAGE, type ImportAttempt } from "@/lib/report-planner-actions";

interface SaveToPlannerProps {
  reportId: string | null;
  itemKind: "idea" | "brief";
  itemIndex: number;
}

/**
 * Import one idea or brief into the planner.
 *
 * The request key is frozen for the life of the attempt, so a double click or
 * a retry after a lost response resolves to the same post. A stale response
 * from a previous account is dropped by the session-binding check.
 */
export function SaveToPlanner({ reportId, itemKind, itemIndex }: SaveToPlannerProps) {
  const router = useRouter();
  const [attempt, setAttempt] = useState<ImportAttempt | null>(null);
  const [requestIdError, setRequestIdError] = useState<string | null>(null);
  const [gate] = useState(createSubmitGate);

  if (!reportId) {
    return (
      <p className="drawer-muted planner-save-note">
        Save this report before importing it into the planner.
      </p>
    );
  }

  async function save() {
    if (!reportId) return;
    if (!gate.acquire()) return;
    let frozen = attempt;
    const session = getSessionStore();
    const binding = session.getSessionBinding();
    setRequestIdError(null);
    try {
      frozen ??= {
        requestId: newRequestId(),
        reportId,
        itemKind,
        itemIndex,
        status: "idle",
        postId: null,
        errorCode: null,
      };
      setAttempt({ ...frozen, status: "saving", errorCode: null });
      const result = await importPlannerPost(
        frozen.requestId,
        frozen.reportId,
        frozen.itemKind,
        frozen.itemIndex,
      );
      const now = session.getSessionBinding();
      if (now.userId !== binding.userId || now.epoch !== binding.epoch) return;
      setAttempt({ ...frozen, status: "saved", postId: result.id });
    } catch (err) {
      const now = session.getSessionBinding();
      if (now.userId !== binding.userId || now.epoch !== binding.epoch) return;
      if (!frozen) {
        setRequestIdError(REQUEST_ID_ERROR_MESSAGE);
        return;
      }
      const code = err instanceof ResearchApiError ? err.code : "unknown_error";
      setAttempt({ ...frozen, status: "failed", errorCode: code });
    } finally {
      gate.release();
    }
  }

  return (
    <div className="planner-save">
      <button
        type="button"
        className="secondary-button"
        onClick={save}
        disabled={attempt?.status === "saving" || attempt?.errorCode === "planner_report_not_found"}
      >
        {attempt?.status === "saved" ? "Saved" : "Save to Planner"}
      </button>
      {requestIdError && (
        <span className="copy-feedback copy-failed" role="status">
          {requestIdError}
        </span>
      )}
      {attempt?.status === "saving" && (
        <span className="copy-feedback" role="status">
          Saving…
        </span>
      )}
      {attempt?.status === "saved" && attempt.postId && (
        <button
          type="button"
          className="secondary-button planner-open-post"
          onClick={() => router.push(`/planner/${attempt.postId}`)}
        >
          Open post
        </button>
      )}
      {attempt?.status === "failed" && (
        <>
          <span className="copy-feedback copy-failed" role="status">
            {attempt.errorCode === "planner_report_not_found"
              ? "This report is no longer available to import."
              : "Could not save to the planner."}
          </span>
          {attempt.errorCode !== "planner_report_not_found" && (
            <button type="button" className="secondary-button" onClick={save}>
              Retry
            </button>
          )}
        </>
      )}
    </div>
  );
}
