"use client";

import { useId, useState } from "react";

import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { filterReferences, referencePlatform, type ReferenceFilters } from "@/lib/report-provenance";
import { ReferenceCard } from "./ReferenceCard";

interface ReferenceListProps {
  references: ResearchReferenceResponse[];
  window?: { date_from?: string; date_to?: string };
}

const INITIAL_VISIBLE = 6;

export function ReferenceList({ references, window }: ReferenceListProps) {
  const id = useId();
  const [filters, setFilters] = useState<ReferenceFilters>({ query: "", platform: "all", date: "all" });
  const [expanded, setExpanded] = useState(false);
  const filtered = filterReferences(references, filters);
  const shown = new Set(expanded ? filtered : filtered.slice(0, INITIAL_VISIBLE));
  const platforms = [...new Set(references.map(referencePlatform))].sort();
  const active = Boolean(filters.query || filters.platform !== "all" || filters.date !== "all");

  function update(next: Partial<ReferenceFilters>) {
    setFilters({ ...filters, ...next });
    setExpanded(false);
  }

  return (
    <section className="reference-list" aria-label="Research references">
      <h2 className="section-title">References</h2>
      <div className="reference-controls" role="group" aria-label="Filter sources">
        <label className="reference-search" htmlFor={`${id}-search`}>
          Search source titles
          <input id={`${id}-search`} type="search" value={filters.query} onChange={(event) => update({ query: event.target.value })} />
        </label>
        <label htmlFor={`${id}-platform`}>
          Platform
          <select id={`${id}-platform`} value={filters.platform} onChange={(event) => update({ platform: event.target.value })}>
            <option value="all">All platforms</option>
            {platforms.map((platform) => <option key={platform} value={platform}>{platform}</option>)}
          </select>
        </label>
        <label htmlFor={`${id}-date`}>
          Publication date
          <select id={`${id}-date`} value={filters.date} onChange={(event) => update({ date: event.target.value as ReferenceFilters["date"] })}>
            <option value="all">All dates</option>
            <option value="dated">Dated</option>
            <option value="undated">Undated / invalid date</option>
          </select>
        </label>
        <button type="button" className="secondary-button" disabled={!active} onClick={() => update({ query: "", platform: "all", date: "all" })}>Reset filters</button>
      </div>
      <p className="section-note reference-result-count" role="status" aria-live="polite">
        {active
          ? `${filtered.length} of ${references.length} sources match.`
          : `${references.length} ${references.length === 1 ? "source" : "sources"}.`}
        {filtered.length > shown.size ? ` Showing ${shown.size}.` : ""}
      </p>
      <p className="report-print-only">Sources: {references.length} total. All sources included; screen filters do not apply.</p>
      {filtered.length === 0 && (
        <p className="drawer-muted reference-no-match">
          {references.length === 0 ? "No source references are available in this report." : "No sources match these filters. Change the title, platform, or date filter, or reset filters."}
        </p>
      )}
      <div className="reference-grid" id={`${id}-results`}>
        {references.map((reference) => (
          <div className="reference-library-entry" hidden={!shown.has(reference)} key={`${reference.source_code}-${reference.content_external_id}`}>
            <ReferenceCard reference={reference} window={window} />
          </div>
        ))}
      </div>
      {filtered.length > INITIAL_VISIBLE && (
        <button type="button" className="secondary-button reference-expand" aria-expanded={expanded} aria-controls={`${id}-results`} onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show fewer sources" : `Show all ${filtered.length} sources`}
        </button>
      )}
    </section>
  );
}
