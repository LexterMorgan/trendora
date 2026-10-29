"use client";

import { useEffect, useRef, useState } from "react";

import {
  EXAMPLE_QUERIES,
  type ResearchDraft,
  type ResearchFormValues,
} from "@/components/ResearchForm";
import { SimpleForm } from "@/components/SimpleForm";
import { Protected } from "@/components/Protected";
import { AppShell } from "@/components/research/AppShell";
import { ResearchHeadline } from "@/components/research/ResearchHeadline";
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
  const [homeFocused, setHomeFocused] = useState(false);
  const [motionEnabled, setMotionEnabled] = useState(false);
  const [typingSignal, setTypingSignal] = useState(0);
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
  const savedMotion = useRef<boolean | null>(null);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    let stored: boolean | null = null;
    try {
      const value = localStorage.getItem("trendora:research-motion");
      if (value === "on") stored = true;
      if (value === "off") stored = false;
    } catch {
      stored = null;
    }
    savedMotion.current = stored;
    const frame = requestAnimationFrame(() => {
      setMotionEnabled(!query.matches && (stored ?? true));
    });

    const onChange = () => {
      if (query.matches) setMotionEnabled(false);
      else setMotionEnabled(savedMotion.current ?? true);
    };
    query.addEventListener("change", onChange);
    return () => {
      cancelAnimationFrame(frame);
      query.removeEventListener("change", onChange);
    };
  }, []);

  function toggleMotion() {
    setMotionEnabled((current) => {
      const next = !current;
      savedMotion.current = next;
      try {
        localStorage.setItem("trendora:research-motion", next ? "on" : "off");
      } catch {
        // The control still works when storage is unavailable.
      }
      return next;
    });
  }

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
    setTypingSignal((value) => value + 1);
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
    <AppShell
      view={view}
      section="Research workspace"
      motionEnabled={motionEnabled}
      onToggleMotion={toggleMotion}
      onNewResearch={handleNewResearch}
      newResearchDisabled={busy}
      typingSignal={typingSignal}
    >
      {view === "home" && (
        <section className="research-stage" aria-labelledby="headline">
          <div className="research-core">
            <div className="research-intro">
              <div className="research-halo" aria-hidden="true" />
              <p className="research-eyebrow">
                <span className="research-eyebrow-dot" aria-hidden="true" />
                Research workspace
              </p>
              <ResearchHeadline
                active={motionEnabled && !homeFocused && !(draft.topic ?? "").trim()}
              />
              <p className="research-lede">Start with a topic. You will review the timeframe next.</p>
            </div>

            <form
              className={`research-composer${homeError ? " is-error" : ""}`}
              onSubmit={handleHomeSubmit}
              noValidate
              onFocus={() => setHomeFocused(true)}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setHomeFocused(false);
                }
              }}
            >
              <label className="sr-only" htmlFor="home-topic">Topic</label>
              <input
                ref={homeTopic}
                id="home-topic"
                type="text"
                value={draft.topic ?? ""}
                onChange={(event) => {
                  setDraft((current) => ({ ...current, topic: event.target.value }));
                  setHomeError(null);
                  setTypingSignal((value) => value + 1);
                }}
                placeholder="What do you want to research?"
                autoComplete="off"
                aria-invalid={homeError ? "true" : undefined}
                aria-describedby={homeError ? "home-topic-error" : undefined}
              />
              {homeError && (
                <p className="research-status" id="home-topic-error" role="alert">
                  <span className="research-status-dot" aria-hidden="true" />
                  {homeError}
                </p>
              )}
              <div className="research-composer-row">
                <span className="research-composer-hint">Timeframe next</span>
                <button type="submit" className="research-send">
                  Continue
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M7 7h10v10M7 17 17 7" />
                  </svg>
                </button>
              </div>
            </form>

            <div className="research-chips" aria-label="Example topics">
              {EXAMPLE_QUERIES.map((query) => (
                <button
                  key={query}
                  type="button"
                  className={draft.topic === query ? "research-chip is-selected" : "research-chip"}
                  aria-pressed={draft.topic === query}
                  onClick={() => handleSuggestion(query)}
                >
                  <span className="research-chip-slash" aria-hidden="true">/</span>
                  {query}
                </button>
              ))}
            </div>

            <p className="research-footnote">
              Research runs on your configured sources. Each report keeps its dates,
              coverage, and citation limits visible.
            </p>
          </div>
        </section>
      )}

      {view === "setup" && (
        <div className="setup-shell research-page">
          <header className="setup-heading">
            <button
              type="button"
              className="text-link"
              onClick={handleBackToStart}
            >
              Back to start
            </button>
            <h1>New research</h1>
            <p>Review the timeframe, then run research.</p>
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
        <div className="results-shell research-page">
          <section className="page-heading">
            <div>
              <h1 id="results-heading" tabIndex={-1}>Research workspace</h1>
              <p>Review your findings or start another question.</p>
            </div>
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
    </AppShell>
  );
}
