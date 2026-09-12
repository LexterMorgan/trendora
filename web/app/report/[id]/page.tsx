"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";

import { getSingleReport, isResearchReport, type ResearchReportResponse } from "@/lib/report-api";
import { ResearchApiError } from "@/lib/trendora-api";
import { ReportView } from "@/components/ReportView";

interface ReportPageProps {
  params: Promise<{ id: string }>;
}

export default function ReportPage({ params }: ReportPageProps) {
  const { id } = use(params);
  const [report, setReport] = useState<ResearchReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  useEffect(() => {
    let active = true;
    getSingleReport(id)
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
  }, [id]);

  return (
    <main className="workspace report-viewer">
      <header className="masthead report-viewer-header">
        <Link className="secondary-button" href="/past-reports">
          ← Past reports
        </Link>
      </header>

      {loading && (
        <p className="loading-note" role="status">
          Loading report…
        </p>
      )}

      {error && (
        <section className="error-state" role="alert">
          <h2 className="section-title">
            {error.code === "not_found" ? "Report not found" : "Could not load report"}
          </h2>
          <p>{error.message}</p>
          <Link className="secondary-button" href="/past-reports">
            Back to past reports
          </Link>
        </section>
      )}

      {!loading && !error && report && <ReportView report={report} />}
    </main>
  );
}
