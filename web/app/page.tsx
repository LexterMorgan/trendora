"use client";

import { useRef, useState } from "react";

import { ResearchForm, type ResearchFormValues } from "@/components/ResearchForm";
import { TurnView, userMessage, type SessionTurn } from "@/components/TurnView";
import { submitReport } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";

export default function Home() {
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [composerKey, setComposerKey] = useState(0);
  const [editValues, setEditValues] = useState<Partial<ResearchFormValues>>({});
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

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
    <main className="workspace">
      <header className="masthead">
        <p className="brand">TRENDORA</p>
        <h1 className="tagline">Social Content Intelligence</h1>
        <p className="subtitle">
          Ask Trendora about real content. Every answer is grounded in the
          supplied evidence.
        </p>
      </header>

      <div className="chat-layout">
        <section className="panel form-panel" aria-label="Research request">
          <h2 className="section-title">Research</h2>
          <ResearchForm
            key={composerKey}
            onSubmit={handleSubmit}
            disabled={busy}
            initialValues={editValues}
          />
        </section>

        <section className="chat-session" aria-live="polite">
          {turns.length === 0 && (
            <div className="session-intro">
              <p className="brand">New session</p>
              <p>
                Submit a research request to start the session. Requests are
                independent and stateless; refreshing the page clears history.
              </p>
            </div>
          )}
          {turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} onEdit={handleEdit} />
          ))}
        </section>
      </div>
    </main>
  );
}
