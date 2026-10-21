"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  listReports,
  ResearchApiError,
  type ReportHistoryFilters,
  type ReportSummaryResponse,
} from "@/lib/trendora-api";
import { ApiErrorPanel, type ApiErrorState } from "@/components/ApiErrorPanel";
import { Header } from "@/components/Header";
import { Protected } from "@/components/Protected";
import { formatDate } from "@/lib/format";

const PAGE_SIZE = 50;

const STATUS_OPTIONS = [
  ["completed", "Completed"],
  ["research_completed", "Research complete"],
  ["no_evidence", "No evidence"],
  ["research_unavailable", "Research unavailable"],
  ["insufficient_evidence", "Limited evidence"],
  ["content_unavailable", "Content unavailable"],
  ["source_data_expired", "Source data expired"],
] as const;

function StatusBadge({ status }: { status: string }) {
  const complete = status === "completed" || status === "research_completed";
  const kind = complete ? "is-completed" : status === "no_evidence" ? "is-no-evidence" : "";
  const labels: Record<string, string> = {
    completed: "Completed",
    research_completed: "Research complete",
    no_evidence: "No evidence",
    research_unavailable: "Research unavailable",
    insufficient_evidence: "Limited evidence",
    content_unavailable: "Content unavailable",
    source_data_expired: "Source data expired",
  };
  const label = labels[status] ?? "Status unavailable";
  return <span className={`status-badge ${kind}`}>{label}</span>;
}

function hasFilters(filters: ReportHistoryFilters): boolean {
  return Boolean(filters.q || filters.status || filters.date_from || filters.date_to);
}

export default function PastReportsPage() {
  return (
    <Protected>
      <PastReportsContent />
    </Protected>
  );
}

function PastReportsContent() {
  const [reports, setReports] = useState<ReportSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiErrorState | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [draft, setDraft] = useState<ReportHistoryFilters>({});
  const [applied, setApplied] = useState<ReportHistoryFilters>({});
  const [validation, setValidation] = useState<string | null>(null);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const filtered = hasFilters(applied);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    listReports({ ...applied, limit: PAGE_SIZE + 1, offset }, { signal: controller.signal })
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
            ? { code: err.code, message: err.message, kind: err.kind }
            : { code: "internal_error", message: "An unexpected error occurred." },
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, applied, reloadKey]);

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setValidation("Start date must not be after end date.");
      return;
    }
    setValidation(null);
    setLoading(true);
    setOffset(0);
    setApplied({
      ...(draft.q?.trim() ? { q: draft.q.trim() } : {}),
      ...(draft.status ? { status: draft.status } : {}),
      ...(draft.date_from ? { date_from: draft.date_from } : {}),
      ...(draft.date_to ? { date_to: draft.date_to } : {}),
    });
  }

  function resetFilters() {
    setValidation(null);
    setLoading(true);
    setDraft({});
    setApplied({});
    setOffset(0);
  }

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
      <Header section="Reports" />
      <section className="page-heading">
        <div>
          <h1>Saved research</h1>
          <p>Return to your findings, sources, and the evidence behind them.</p>
        </div>
        {reports.length > 0 && <Link className="primary-button" href="/">New research</Link>}
      </section>

      <form className="history-filters" onSubmit={applyFilters} aria-label="Filter saved reports">
        <div className="history-filter-field">
          <label htmlFor="history-search">Topic search</label>
          <input
            id="history-search"
            type="search"
            maxLength={200}
            value={draft.q ?? ""}
            onChange={(event) => setDraft({ ...draft, q: event.target.value })}
            placeholder="Literal text in the topic"
          />
        </div>
        <div className="history-filter-field">
          <label htmlFor="history-status">Saved outcome</label>
          <select
            id="history-status"
            value={draft.status ?? ""}
            onChange={(event) => setDraft({ ...draft, status: event.target.value || undefined })}
          >
            <option value="">All outcomes</option>
            {STATUS_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
        <div className="history-filter-field">
          <label htmlFor="history-date-from">Requested from</label>
          <input
            id="history-date-from"
            type="date"
            value={draft.date_from ?? ""}
            onChange={(event) => setDraft({ ...draft, date_from: event.target.value || undefined })}
          />
        </div>
        <div className="history-filter-field">
          <label htmlFor="history-date-to">Requested to</label>
          <input
            id="history-date-to"
            type="date"
            value={draft.date_to ?? ""}
            onChange={(event) => setDraft({ ...draft, date_to: event.target.value || undefined })}
          />
        </div>
        <div className="history-filter-actions">
          <button type="submit" className="primary-button">Apply filters</button>
          <button type="button" className="secondary-button" onClick={resetFilters}>
            Reset
          </button>
        </div>
        <p className="section-note history-filter-note">
          Outcome is the status stored when the report was saved. Source-data
          retention can later replace it with expired. Dates overlap the
          report&apos;s requested timeframe, not its save date.
        </p>
        {validation && <p className="form-error" role="alert">{validation}</p>}
      </form>

      {loading && (
        <p className="loading-note" role="status">
          Loading reports…
        </p>
      )}

      {error && (
        <ApiErrorPanel error={error} title="Could not load reports" onRetry={retry} />
      )}

      {!loading && !error && reports.length === 0 && filtered && (
        <section className="empty-state" aria-label="No matching reports">
          <h2 className="section-title">No reports match these filters</h2>
          <p>Try a shorter topic search, another outcome, or a wider requested timeframe.</p>
          <button type="button" className="secondary-button" onClick={resetFilters}>
            Clear filters
          </button>
        </section>
      )}

      {!loading && !error && reports.length === 0 && !filtered && (
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
                  <span className="history-markets">{report.markets.length ? report.markets.join(", ") : "Global"}</span>
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
