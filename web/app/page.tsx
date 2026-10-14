"use client";

import { useEffect, useRef, useState } from "react";

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
    const turn: SessionTurn = {
      id,
      request: values,
      state: "loading",
      report: null,
      error: null,
    };
    setTurns((current) => [...current, turn]);
    setEditValues({});

    try {
      const report = await submitReport(values);
      setTurns((current) =>
        current.map((item) => (item.id === id ? { ...item, state: "success", report } : item)),
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

      {emptySession ? (
        <div className="start-sheet">
          <header className="start-masthead">
            <h1 className="start-headline">
              Understand what’s happening in your topics.
            </h1>
            <p className="start-subtitle">
              Search available sources, read sourced findings with their
              publication dates, and see where coverage is thin. Content ideas
              and briefs stay optional.
            </p>
          </header>

          <section className="panel start-composer" aria-label="Research request">
            <SimpleForm
              key={composerKey}
              onSubmit={handleSubmit}
              disabled={busy}
              initialValues={editValues}
            />
          </section>
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
