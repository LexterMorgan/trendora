"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { listReports, ResearchApiError, type ReportSummaryResponse } from "@/lib/trendora-api";
import { Header } from "@/components/Header";
import { formatDate } from "@/lib/format";

const PAGE_SIZE = 50;

function StatusBadge({ status }: { status: string }) {
  const kind = status === "completed" ? "is-completed" : status === "no_evidence" ? "is-no-evidence" : "";
  const label = status === "completed" ? "Completed" : status === "no_evidence" ? "No evidence" : status;
  return <span className={`status-badge ${kind}`}>{label}</span>;
}

export default function PastReportsPage() {
  const [reports, setReports] = useState<ReportSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const page = Math.floor(offset / PAGE_SIZE) + 1;

  useEffect(() => {
    let active = true;
    listReports({ limit: PAGE_SIZE + 1, offset })
      .then((data) => {
        if (!active) return;
        setHasMore(data.length > PAGE_SIZE);
        setReports(data.slice(0, PAGE_SIZE));
        setError(null);
      })
      .catch((err) => {
        if (!active) return;
        setReports([]);
        setError(
          err instanceof ResearchApiError
            ? { code: err.code, message: err.message }
            : { code: "internal_error", message: "An unexpected error occurred." },
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [offset, reloadKey]);

  function goTo(newOffset: number) {
    setOffset(newOffset);
    setLoading(true);
  }

  function retry() {
    setLoading(true);
    setReloadKey((key) => key + 1);
  }

  return (
    <main className="workspace history-workspace">
      <Header
        section="Past Reports"
        actionLink={{ href: "/", label: "New research" }}
      />

      {loading && (
        <p className="loading-note" role="status">
          Loading reports…
        </p>
      )}

      {error && (
        <section className="error-state" role="alert">
          <h2 className="section-title">Could not load reports</h2>
          <p>{error.message}</p>
          <button type="button" className="secondary-button" onClick={retry}>
            Retry
          </button>
        </section>
      )}

      {!loading && !error && reports.length === 0 && (
        <section className="empty-state" aria-label="No past reports">
          <h2 className="section-title">No reports yet</h2>
          <p>Start your first research run and it will appear here.</p>
          <Link className="primary-button" href="/">
            Generate research report
          </Link>
        </section>
      )}

      {!loading && !error && reports.length > 0 && (
        <>
          <ul className="history-list">
            {reports.map((report) => (
              <li key={report.id}>
                <Link className="history-row" href={`/report/${report.id}`}>
                  <span className="history-date">{formatDate(report.created_at)}</span>
                  <span className="history-topic">{report.topic}</span>
                  <span className="history-markets">{report.markets.join(", ")}</span>
                  <StatusBadge status={report.status} />
                </Link>
              </li>
            ))}
          </ul>

          <nav className="history-pagination" aria-label="Pagination">
            <button
              type="button"
              className="secondary-button"
              disabled={offset === 0}
              onClick={() => goTo(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            <span className="history-page-label">Page {page}</span>
            <button
              type="button"
              className="secondary-button"
              disabled={!hasMore}
              onClick={() => goTo(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
