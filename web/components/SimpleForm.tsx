"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  DATE_PRESETS,
  DEFAULT_RESULT_LIMIT,
  GLOBAL_COVERAGE_NOTE,
  presetRange,
  todayISODate,
  toISODate,
  type ResearchDraft,
  type ResearchFormValues,
} from "@/components/ResearchForm";

interface SimpleFormProps {
  onSubmit: (values: ResearchFormValues) => void;
  disabled: boolean;
  initialValues?: ResearchDraft;
  initialPreset?: string;
  onDraftChange?: (draft: ResearchDraft) => void;
}

/**
 * Simplified research request: topic + timeframe, run globally across the
 * configured topic-search sources. No country, source, or depth selection.
 * Research runs first; content ideas and briefs are generated on demand from
 * the completed report.
 */
export function SimpleForm({ onSubmit, disabled, initialValues, initialPreset, onDraftChange }: SimpleFormProps) {
  const [topic, setTopic] = useState(initialValues?.topic ?? "");
  const [localError, setLocalError] = useState<string | null>(null);

  const [preset, setPreset] = useState<string>(initialPreset ?? (initialValues?.date_from || initialValues?.date_to ? "custom" : "last_30d"));
  const [dateFrom, setDateFrom] = useState<string>(initialValues?.date_from ?? "");
  const [dateTo, setDateTo] = useState<string>(initialValues?.date_to ?? "");
  const [maxDate, setMaxDate] = useState<string>("");

  useEffect(() => {
    onDraftChange?.({
      topic,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      preset,
    });
  }, [topic, dateFrom, dateTo, preset, onDraftChange]);

  function refreshMaxDate() {
    setMaxDate(todayISODate());
  }

  function handleDateFromChange(value: string) {
    setDateFrom(value);
    setPreset("custom");
  }

  function handleDateToChange(value: string) {
    setDateTo(value);
    setPreset("custom");
  }

  function handlePresetChange(value: string) {
    setPreset(value);
    const today = new Date();
    const localToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    setMaxDate(todayISODate());
    const range = presetRange(value, localToday);
    if (range) {
      setDateFrom(toISODate(range.from));
      setDateTo(toISODate(range.to));
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) {
      setLocalError("Please enter a topic or keyword.");
      return;
    }
    if ((dateFrom && !dateTo) || (!dateFrom && dateTo)) {
      setLocalError("Enter both From and To dates, or leave both blank.");
      return;
    }
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setLocalError("Start date must not be after end date.");
      return;
    }
    const today = todayISODate();
    if ((dateFrom && dateFrom > today) || (dateTo && dateTo > today)) {
      setLocalError("Dates must not be in the future.");
      return;
    }
    setLocalError(null);

    // Global request: no markets, both configured topic-search sources, a
    // fixed result budget. An empty markets list is the global signal.
    const values: ResearchFormValues = {
      topic: topic.trim(),
      markets: [],
      sources: ["youtube", "public_web"],
      result_limit: DEFAULT_RESULT_LIMIT,
      include_content_tools: false,
    };
    // Only send an explicit window when the user actually set one; otherwise
    // omit the fields so the adapter applies its default last-30-days window.
    // Sending empty strings would fail date parsing.
    if (dateFrom && dateTo) {
      values.date_from = dateFrom;
      values.date_to = dateTo;
    }
    onSubmit(values);
  }

  return (
    <form className="research-form simple-research-form" onSubmit={handleSubmit} aria-busy={disabled}>
      <div className="form-field topic-field">
        <label htmlFor="topic">Topic</label>
        <input
          id="topic"
          type="text"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="What topic do you want to research?"
          required
          disabled={disabled}
        />
      </div>

      <fieldset className="date-fieldset" aria-describedby="date-range-help">
        <legend>Timeframe</legend>
        <div className="form-field">
          <label htmlFor="simple-date-preset">Preset</label>
          <select
            id="simple-date-preset"
            value={preset}
            onChange={(event) => handlePresetChange(event.target.value)}
            disabled={disabled}
          >
            {DATE_PRESETS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
        <p className="date-help" id="date-range-help">
          Blank dates use the last 30 days. Choose a preset or enter both dates
          for a different range.
        </p>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="simple-date-from">From</label>
            <input
              id="simple-date-from"
              type="date"
              value={dateFrom}
              max={maxDate}
              onFocus={refreshMaxDate}
              onChange={(event) => handleDateFromChange(event.target.value)}
              disabled={disabled}
            />
          </div>
          <div className="form-field">
            <label htmlFor="simple-date-to">To</label>
            <input
              id="simple-date-to"
              type="date"
              value={dateTo}
              max={maxDate}
              onFocus={refreshMaxDate}
              onChange={(event) => handleDateToChange(event.target.value)}
              disabled={disabled}
            />
          </div>
        </div>
      </fieldset>

      <p className="date-help content-on-demand-note">
        Content ideas and briefs can be generated from the saved report after research.
      </p>

      <button type="submit" className="primary-button" disabled={disabled}>
        {disabled ? "Generating report…" : "Generate research report"}
      </button>

      <p className="composer-explore">
        Want to inspect indexed titles and snippets before generating a report?
      </p>
      <Link className="composer-explore-link" href="/discover">
        Explore sources
      </Link>

      {localError && (
        <p className="form-error" role="alert">
          {localError}
        </p>
      )}

      <p className="date-help source-coverage-note">{GLOBAL_COVERAGE_NOTE}</p>
    </form>
  );
}
