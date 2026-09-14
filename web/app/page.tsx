"use client";

import { useRef, useState } from "react";
import Link from "next/link";

import { type ResearchFormValues } from "@/components/ResearchForm";
import { SimpleForm } from "@/components/SimpleForm";
import { Header } from "@/components/Header";
import { TurnView, userMessage, type SessionTurn } from "@/components/TurnView";
import { submitReport } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";

export default function Home() {
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [composerKey, setComposerKey] = useState(0);
  const [editValues, setEditValues] = useState<Partial<ResearchFormValues>>({});
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const emptySession = turns.length === 0;

  async function handleSubmit(values: ResearchFormValues) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);

    const id = Date.now();
    const turn: SessionTurn = {
      id,
      request: values,
      userMessage: userMessage(values),
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
          ? { code: err.code, message: err.message }
          : { code: "internal_error", message: "An unexpected error occurred." };
      setTurns((current) =>
        current.map((item) => (item.id === id ? { ...item, state: "error", error } : item)),
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function handleEdit(request: ResearchFormValues) {
    setEditValues({ ...request });
    setComposerKey((key) => key + 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <main className={emptySession ? "workspace canvas-mode" : "workspace"}>
      {emptySession ? (
        <div className="session-canvas">
          <div className="canvas-content">
            <header className="canvas-masthead">
              <p className="brand">TRENDORA</p>
              <h1 className="canvas-headline">
                Turn social signals into content decisions.
              </h1>
              <p className="canvas-subtitle">
                Every result traces back to real source evidence — references,
                citations, and full provenance are surfaced with each answer.
              </p>
              <Link className="secondary-button history-link" href="/past-reports">
                Past reports
              </Link>
            </header>

            <section className="composer-panel" aria-label="Research request">
              <SimpleForm
                key={composerKey}
                onSubmit={handleSubmit}
                disabled={busy}
                initialValues={editValues}
                showExamples
              />
            </section>
          </div>
        </div>
      ) : (
        <>
          <Header
            section="Research Workspace"
            actionLink={{ href: "/past-reports", label: "Past reports" }}
          />

          <div className="chat-layout">
            <section className="panel form-panel" aria-label="Research request">
              <h2 className="section-title">Research</h2>
              <SimpleForm
                key={composerKey}
                onSubmit={handleSubmit}
                disabled={busy}
                initialValues={editValues}
              />
            </section>

            <section className="chat-session" aria-live="polite">
              {turns.map((turn) => (
                <TurnView key={turn.id} turn={turn} onEdit={handleEdit} />
              ))}
            </section>
          </div>
        </>
      )}
    </main>
  );
}