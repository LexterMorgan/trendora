"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";

import { getSingleReport, isResearchReport, type ResearchReportResponse } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";
import { ApiErrorPanel, type ApiErrorState } from "@/components/ApiErrorPanel";
import { Header } from "@/components/Header";
import { Protected } from "@/components/Protected";
import { ReportView } from "@/components/ReportView";

interface ReportPageProps {
  params: Promise<{ id: string }>;
}

export default function ReportPage({ params }: ReportPageProps) {
  const { id } = use(params);
  return (
    <Protected>
      <ReportContent id={id} />
    </Protected>
  );
}

function ReportContent({ id }: { id: string }) {
  const [report, setReport] = useState<ResearchReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiErrorState | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    getSingleReport(id, { signal: controller.signal })
      .then((data) => {
        if (!active) return;
        setReport(isResearchReport(data) ? data : null);
        setError(null);
      })
      .catch((err) => {
        if (!active) return;
        setReport(null);
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
  }, [id, reloadKey]);

  function retry() {
    setLoading(true);
    setReloadKey((key) => key + 1);
  }

  const topic = report?.research.query?.topic;
  const section = topic ? `Report: ${topic}` : "Report";

  return (
    <main className="workspace report-viewer">
      <Header section={section} />

      {loading && (
        <p className="loading-note" role="status">
          Loading report…
        </p>
      )}

      {error && (
        <ApiErrorPanel
          error={error}
          title={error.code === "not_found" ? "Report not found" : "Could not load report"}
          onRetry={retry}
        >
          <Link className="secondary-button" href="/past-reports">
            Back to past reports
          </Link>
        </ApiErrorPanel>
      )}

      {!loading && !error && report && (
        <>
          <section className="page-heading report-heading">
            <div>
              <Link className="report-back-link" href="/past-reports">All reports</Link>
              <h1>{topic || "Research report"}</h1>
              <p>Findings, original sources, and a record of what was searched.</p>
            </div>
          </section>
          <ReportView
            key={id}
            report={report}
            onReportUpdated={(updated) => {
              setReport(updated);
              const nextId = updated.persistence?.report_id;
              if (nextId && typeof window !== "undefined") {
                window.history.replaceState(null, "", `/report/${nextId}`);
              }
            }}
          />
        </>
      )}
    </main>
  );
}
