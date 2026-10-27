"use client";

import { useEffect, useRef, useState } from "react";

import {
  EXAMPLE_QUERIES,
  type ResearchDraft,
  type ResearchFormValues,
} from "@/components/ResearchForm";
import { SimpleForm } from "@/components/SimpleForm";
import { Header } from "@/components/Header";
import { Protected } from "@/components/Protected";
import { TurnView, type SessionTurn } from "@/components/TurnView";
import { submitReport } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";
import { createSubmitGate } from "@/lib/submit-gate";

export default function Home() {
  return (
    <Protected>
      <Workspace />
    </Protected>
  );
}

type WorkspaceView = "home" | "setup" | "results";

function Workspace() {
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [view, setView] = useState<WorkspaceView>("home");
  const [composerKey, setComposerKey] = useState(0);
  const [draft, setDraft] = useState<ResearchDraft>({ topic: "" });
  const [homeError, setHomeError] = useState<string | null>(null);
  const [cancelledNotice, setCancelledNotice] = useState(false);
  const [savedTurnIds, setSavedTurnIds] = useState<Set<number>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [gate] = useState(createSubmitGate);
  const focusAfterEdit = useRef(false);
  const focusHomeAfterReturn = useRef(false);
  const focusResultsAfterTurn = useRef(false);
  const homeTopic = useRef<HTMLInputElement>(null);
  const pending = useRef<{
    id: number;
    controller: AbortController;
    request: ResearchFormValues;
  } | null>(null);
  const nextTurnId = useRef(0);

  useEffect(() => () => {
    pending.current?.controller.abort();
    pending.current = null;
    gate.release();
  }, [gate]);

  useEffect(() => {
    if (view !== "home" || !focusHomeAfterReturn.current) return;
    focusHomeAfterReturn.current = false;
    homeTopic.current?.focus();
  }, [view]);

  useEffect(() => {
    if (!focusResultsAfterTurn.current) return;
    focusResultsAfterTurn.current = false;
    document.getElementById("results-heading")?.focus();
  }, [turns]);

  function openSetup(next: ResearchDraft, focus: "preset" | "topic" = "preset") {
    setDraft(next);
    setCancelledNotice(false);
    setView("setup");
    setComposerKey((key) => key + 1);
    requestAnimationFrame(() => {
      document.getElementById(focus === "preset" ? "simple-date-preset" : "topic")?.focus();
    });
  }

  function handleHomeSubmit(event: React.FormEvent) {
    event.preventDefault();
    const topic = (draft.topic ?? "").trim();
    if (!topic) {
      setHomeError("Enter a topic to continue.");
      homeTopic.current?.focus();
      return;
    }
    setHomeError(null);
    openSetup({ ...draft, topic });
  }

  function handleSuggestion(query: string) {
    setDraft((current) => ({ ...current, topic: query }));
    setHomeError(null);
    requestAnimationFrame(() => homeTopic.current?.focus());
  }

  function handleBackToStart() {
    setView("home");
    focusHomeAfterReturn.current = true;
  }

  function handleReportUpdated(turnId: number, report: import("@/lib/report-api").ResearchReportResponse) {
    setTurns((current) =>
      current.map((turn) => (turn.id === turnId ? { ...turn, report } : turn)),
    );
  }

  function handleReportSaved(turnId: number) {
    setSavedTurnIds((current) => {
      const next = new Set(current);
      next.add(turnId);
      return next;
    });
  }

  function handleNewResearch() {
    if (busy) return;
    const unsaved = turns.some(
      (turn) =>
        turn.state === "success" &&
        turn.report?.persistence?.status !== "saved" &&
        !savedTurnIds.has(turn.id),
    );
    const unfinished = turns.some((turn) => turn.state === "error");
    const message = unsaved
      ? "This report was not saved. Starting a new research request will remove it from this screen. Continue?"
      : unfinished
        ? "This research attempt has not completed. Starting a new research request will clear it from this screen. Continue?"
        : null;
    if (message && !window.confirm(message)) return;
    setTurns([]);
    setSavedTurnIds(new Set());
    setDraft({ topic: "" });
    setHomeError(null);
    setCancelledNotice(false);
    setComposerKey((key) => key + 1);
    focusHomeAfterReturn.current = true;
    setView("home");
  }

  async function handleSubmit(values: ResearchFormValues) {
    if (!gate.acquire()) return;
    const controller = new AbortController();
    const id = ++nextTurnId.current;
    const startedAt = Date.now();
    pending.current?.controller.abort();
    pending.current = { id, controller, request: values };
    setBusy(true);

    const turn: SessionTurn = {
      id,
      request: values,
      state: "loading",
      report: null,
      error: null,
      startedAt,
    };
    setTurns((current) => [...current, turn]);
    setCancelledNotice(false);
    setView("results");

    try {
      const report = await submitReport(values, { signal: controller.signal });
      if (pending.current?.id !== id || controller.signal.aborted) return;
      const clientElapsedMs = Date.now() - startedAt;
      focusResultsAfterTurn.current = true;
      setTurns((current) =>
        current.map((item) =>
          item.id === id ? { ...item, state: "success", report, clientElapsedMs } : item,
        ),
      );
    } catch (err) {
      if (
        pending.current?.id !== id ||
        controller.signal.aborted ||
        (err instanceof Error && err.name === "AbortError")
      ) return;
      const error =
        err instanceof ResearchApiError
          ? { code: err.code, message: err.message, kind: err.kind }
          : { code: "internal_error", message: "An unexpected error occurred." };
      focusResultsAfterTurn.current = true;
      setTurns((current) =>
        current.map((item) => (item.id === id ? { ...item, state: "error", error } : item)),
      );
    } finally {
      if (pending.current?.id === id) {
        pending.current = null;
        gate.release();
        setBusy(false);
      }
    }
  }

  function handleCancel() {
    const current = pending.current;
    if (!current) return;
    pending.current = null;
    current.controller.abort();
    gate.release();
    setBusy(false);
    setTurns((items) =>
      items.map((item) =>
        item.id === current.id
          ? { ...item, state: "cancelled", error: null }
          : item,
      ),
    );
    setDraft({ ...current.request });
    setCancelledNotice(true);
    setView("setup");
    setComposerKey((key) => key + 1);
    requestAnimationFrame(() => document.getElementById("topic")?.focus());
  }

  function handleEdit(request: ResearchFormValues) {
    setDraft({ ...request });
    setCancelledNotice(false);
    setView("setup");
    focusAfterEdit.current = true;
    setComposerKey((key) => key + 1);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
  }

  // The composer is remounted after an edit, so move focus to the topic field
  // the user asked to change. Editing never submits on its own.
  useEffect(() => {
    if (!focusAfterEdit.current) return;
    focusAfterEdit.current = false;
    const topic = document.getElementById("topic");
    topic?.focus();
    if (topic instanceof HTMLInputElement) topic.select();
  }, [composerKey]);

  return (
    <main className="workspace">
      <Header section="Research Workspace" />

      {view === "home" && (
        <section className="home-start" aria-labelledby="home-start-title">
          <div className="home-start-inner">
            <h1 id="home-start-title">What would you like to research?</h1>
            <p>Start with a topic. You will review the timeframe next.</p>
            <form className="home-form" onSubmit={handleHomeSubmit} noValidate>
              <div className="form-field home-topic-field">
                <label htmlFor="home-topic">Topic</label>
                <input
                  ref={homeTopic}
                  id="home-topic"
                  type="text"
                  value={draft.topic ?? ""}
                  onChange={(event) => {
                    setDraft((current) => ({ ...current, topic: event.target.value }));
                    setHomeError(null);
                  }}
                  placeholder="What do you want to research?"
                  autoComplete="off"
                  aria-invalid={homeError ? "true" : undefined}
                  aria-describedby={homeError ? "home-topic-error" : undefined}
                />
                {homeError && (
                  <p className="form-error" id="home-topic-error" role="alert">
                    {homeError}
                  </p>
                )}
              </div>
              <button type="submit" className="primary-button">
                Continue
              </button>
            </form>
            <div className="home-suggestions" aria-label="Example topics">
              <span className="form-label">Example topics</span>
              <div className="example-queries">
                {EXAMPLE_QUERIES.map((query) => (
                  <button
                    key={query}
                    type="button"
                    className={draft.topic === query ? "example-query is-selected" : "example-query"}
                    aria-pressed={draft.topic === query}
                    onClick={() => handleSuggestion(query)}
                  >
                    {query}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {view === "setup" && (
        <div className="setup-shell">
          <header className="setup-heading">
            <button
              type="button"
              className="text-link"
              onClick={handleBackToStart}
            >
              Back to start
            </button>
            <h1>New research</h1>
            <p>Review the timeframe and optional content tools, then run research.</p>
          </header>
          {cancelledNotice && (
            <p className="loading-note setup-notice" role="status">
              Stopped waiting. The run may continue, and a saved report may still
              appear in Reports.
            </p>
          )}
          <section className="panel setup-panel" aria-label="Research request">
            <SimpleForm
              key={composerKey}
              onSubmit={handleSubmit}
              disabled={busy}
              initialValues={draft}
              initialPreset={draft.preset}
              onDraftChange={setDraft}
            />
          </section>
        </div>
      )}

      {view === "results" && (
        <div className="results-shell">
          <section className="page-heading">
            <div>
              <h1 id="results-heading" tabIndex={-1}>Research workspace</h1>
              <p>Review your findings or start another question.</p>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={handleNewResearch}
              disabled={busy}
            >
              New research
            </button>
          </section>
          <section className="chat-session" aria-live="polite">
            {turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                onEdit={handleEdit}
                onRetry={handleSubmit}
                onCancel={handleCancel}
                onReportSaved={handleReportSaved}
                onReportUpdated={handleReportUpdated}
              />
            ))}
          </section>
        </div>
      )}
    </main>
  );
}
