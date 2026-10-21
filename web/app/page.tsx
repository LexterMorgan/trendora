"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { type ResearchFormValues } from "@/components/ResearchForm";
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

function Workspace() {
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [composerKey, setComposerKey] = useState(0);
  const [editValues, setEditValues] = useState<Partial<ResearchFormValues>>({});
  const [busy, setBusy] = useState(false);
  const [gate] = useState(createSubmitGate);
  const focusAfterEdit = useRef(false);
  const emptySession = turns.length === 0;

  async function handleSubmit(values: ResearchFormValues) {
    if (!gate.acquire()) return;
    setBusy(true);

    const id = Date.now();
    const startedAt = id;
    const turn: SessionTurn = {
      id,
      request: values,
      state: "loading",
      report: null,
      error: null,
      startedAt,
    };
    setTurns((current) => [...current, turn]);
    setEditValues({});

    try {
      const report = await submitReport(values);
      const clientElapsedMs = Date.now() - startedAt;
      setTurns((current) =>
        current.map((item) =>
          item.id === id ? { ...item, state: "success", report, clientElapsedMs } : item,
        ),
      );
    } catch (err) {
      const error =
        err instanceof ResearchApiError
          ? { code: err.code, message: err.message, kind: err.kind }
          : { code: "internal_error", message: "An unexpected error occurred." };
      setTurns((current) =>
        current.map((item) => (item.id === id ? { ...item, state: "error", error } : item)),
      );
    } finally {
      gate.release();
      setBusy(false);
    }
  }

  function handleEdit(request: ResearchFormValues) {
    setEditValues({ ...request });
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

      {!emptySession && (
        <section className="page-heading">
          <div>
            <h1>Research workspace</h1>
            <p>Review your findings or start another question.</p>
          </div>
        </section>
      )}

      {emptySession ? (
        <div className="start-sheet">
          <header className="start-masthead">
            <h1 className="start-headline">
              Research with the evidence in view.
            </h1>
            <p className="start-subtitle">
              Search YouTube and the public web. Read sourced findings,
              inspect their citations, and save your research.
            </p>
          </header>

          <div className="start-workbench">
            <section className="panel start-composer" aria-label="Research request">
              <div className="composer-heading">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" />
                </svg>
                <h2>New research</h2>
              </div>
              <SimpleForm
                key={composerKey}
                onSubmit={handleSubmit}
                disabled={busy}
                initialValues={editValues}
              />
            </section>

            <aside className="research-guide" aria-labelledby="research-guide-title">
              <h2 id="research-guide-title">Start with the source.</h2>
              <p>Every report keeps the findings and the material behind them together.</p>
              <div className="guide-source">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <rect x="3" y="5" width="18" height="14" rx="4" /><path d="m10 9 5 3-5 3Z" />
                </svg>
                <div><h3>YouTube</h3><p>Video titles, descriptions, and available metrics.</p></div>
              </div>
              <div className="guide-source">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z" />
                </svg>
                <div><h3>Public web</h3><p>Indexed titles and snippets. Publication dates can be unknown.</p></div>
              </div>
              <p className="guide-note">Search limits and date uncertainty stay visible in your report.</p>
              <nav className="guide-links" aria-label="Research shortcuts">
                <Link href="/past-reports">
                  <span><strong>Saved research</strong><span>Pick up where you left off</span></span>
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
                </Link>
                <Link href="/planner">
                  <span><strong>Shared planner</strong><span>Turn your research into a draft</span></span>
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
                </Link>
              </nav>
            </aside>
          </div>
        </div>
      ) : (
        <div className="chat-layout">
          <section className="panel form-panel" aria-label="Research request">
            <h2 className="section-title">New research</h2>
            <SimpleForm
              key={composerKey}
              onSubmit={handleSubmit}
              disabled={busy}
              initialValues={editValues}
            />
          </section>

          <section className="chat-session" aria-live="polite">
            {turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                onEdit={handleEdit}
                onRetry={handleSubmit}
              />
            ))}
          </section>
        </div>
      )}
    </main>
  );
}
