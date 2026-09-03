"use client";

import { useState } from "react";

export const MARKETS: { code: string; label: string }[] = [
  { code: "ID", label: "Indonesia" },
  { code: "TH", label: "Thailand" },
  { code: "MY", label: "Malaysia" },
  { code: "SG", label: "Singapore" },
  { code: "VN", label: "Vietnam" },
  { code: "PH", label: "Philippines" },
];

export const RESEARCH_DEPTHS = [
  { value: 10, label: "Quick" },
  { value: 20, label: "Standard" },
  { value: 50, label: "Deep" },
] as const;

export function depthWording(resultLimit: number): string {
  const depth = RESEARCH_DEPTHS.find((entry) => entry.value === resultLimit);
  if (depth) return `${depth.label} — ${depth.value} references`;
  return `${resultLimit} references`;
}

export const EXAMPLE_QUERIES = [
  "AI education tools for students",
  "Online learning platform trends",
  "STEM scholarships in Southeast Asia",
];

export const DATE_PRESETS = [
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_30d", label: "Last 30 days" },
  { value: "last_90d", label: "Last 90 days" },
  { value: "last_12m", label: "Last 12 months" },
  { value: "custom", label: "Custom" },
];

export const SOURCE_ROADMAP = [
  { code: "youtube", name: "YouTube", status: "Available", note: null, disabled: false },
  { code: "facebook", name: "Facebook", status: "Priority next", note: "connection required", disabled: true },
  { code: "instagram", name: "Instagram", status: "Planned", note: "connection required", disabled: true },
  { code: "tiktok", name: "TikTok", status: "Planned", note: "access-dependent", disabled: true },
];

export interface ResearchFormValues {
  topic: string;
  market: string;
  date_from: string;
  date_to: string;
  sources: string[];
  result_limit: number;
}

/* Local-calendar date helpers. Never UTC, never hardcoded years. */

function todayLocal(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function toISODate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function daysAgoLocal(today: Date, offset: number): Date {
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
}

function oneYearEarlier(value: Date): Date {
  const year = value.getFullYear() - 1;
  const month = value.getMonth();
  const day = value.getDate();
  const shifted = new Date(year, month, day);
  if (shifted.getDate() !== day) {
    // e.g. Feb 29 in a leap year, year before is not leap: clamp to Feb 28.
    return new Date(year, month + 1, 0);
  }
  return shifted;
}

export function presetRange(
  preset: string,
  today: Date,
): { from: Date; to: Date } | null {
  switch (preset) {
    case "last_7d":
      return { from: daysAgoLocal(today, 6), to: today };
    case "last_30d":
      return { from: daysAgoLocal(today, 29), to: today };
    case "last_90d":
      return { from: daysAgoLocal(today, 89), to: today };
    case "last_12m":
      return { from: oneYearEarlier(today), to: today };
    default:
      return null;
  }
}

interface ResearchFormProps {
  onSubmit: (values: ResearchFormValues) => void;
  disabled: boolean;
  initialValues?: Partial<ResearchFormValues>;
  showExamples?: boolean;
}

function safeDepth(value: number | undefined): number {
  if (value !== undefined && RESEARCH_DEPTHS.some((entry) => entry.value === value)) return value;
  return 20;
}

export function ResearchForm({ onSubmit, disabled, initialValues, showExamples }: ResearchFormProps) {
  const [topic, setTopic] = useState(initialValues?.topic ?? "");
  const [market, setMarket] = useState(initialValues?.market ?? "SG");
  const [resultLimit, setResultLimit] = useState<number>(() =>
    safeDepth(initialValues?.result_limit),
  );
  const [localError, setLocalError] = useState<string | null>(null);

  const [preset, setPreset] = useState<string>(() => {
    if (initialValues?.date_from || initialValues?.date_to) return "custom";
    return "custom";
  });
  const [dateFrom, setDateFrom] = useState<string>(() => {
    return initialValues?.date_from ?? "";
  });
  const [dateTo, setDateTo] = useState<string>(() => {
    return initialValues?.date_to ?? "";
  });
  const [maxDate, setMaxDate] = useState<string>("");

  function refreshMaxDate() {
    setMaxDate(toISODate(todayLocal()));
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
    const today = todayLocal();
    setMaxDate(toISODate(today));
    const range = presetRange(value, today);
    if (range) {
      setDateFrom(toISODate(range.from));
      setDateTo(toISODate(range.to));
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setLocalError("Start date must not be after end date.");
      return;
    }
    const today = toISODate(todayLocal());
    if ((dateFrom && dateFrom > today) || (dateTo && dateTo > today)) {
      setLocalError("Dates must not be in the future.");
      return;
    }
    setLocalError(null);
    onSubmit({
      topic: topic.trim(),
      market,
      date_from: dateFrom,
      date_to: dateTo,
      sources: ["youtube"],
      result_limit: resultLimit,
    });
  }

  return (
    <form className="research-form" onSubmit={handleSubmit}>
      <div className="form-field topic-field">
        <label htmlFor="topic">Topic</label>
        <input
          id="topic"
          type="text"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="What content topic do you want to research?"
          required
          disabled={disabled}
        />
      </div>

      {showExamples && (
        <div className="form-field" aria-label="Example topics">
          <span className="form-label">Example topics</span>
          <div className="example-queries">
            {EXAMPLE_QUERIES.map((query) => (
              <button
                key={query}
                type="button"
                className={topic === query ? "example-query is-selected" : "example-query"}
                aria-pressed={topic === query}
                disabled={disabled}
                onClick={() => setTopic(query)}
              >
                {query}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="market">Market</label>
          <select
            id="market"
            value={market}
            onChange={(event) => setMarket(event.target.value)}
            disabled={disabled}
          >
            {MARKETS.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="research-depth">Research depth</label>
          <select
            id="research-depth"
            value={resultLimit}
            onChange={(event) => setResultLimit(Number(event.target.value))}
            disabled={disabled}
          >
            {RESEARCH_DEPTHS.map((depth) => (
              <option key={depth.value} value={depth.value}>
                {depth.label} — {depth.value} references
              </option>
            ))}
          </select>
        </div>
      </div>

      <fieldset className="date-fieldset">
        <legend>Date range</legend>
        <div className="form-field">
          <label htmlFor="date-preset">Preset</label>
          <select
            id="date-preset"
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
        <p className="date-help">
          Presets update both dates. Editing either date switches to Custom.
        </p>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="date-from">From</label>
            <input
              id="date-from"
              type="date"
              value={dateFrom}
              max={maxDate}
              onFocus={refreshMaxDate}
              onChange={(event) => handleDateFromChange(event.target.value)}
              required
              disabled={disabled}
            />
          </div>
          <div className="form-field">
            <label htmlFor="date-to">To</label>
            <input
              id="date-to"
              type="date"
              value={dateTo}
              max={maxDate}
              onFocus={refreshMaxDate}
              onChange={(event) => handleDateToChange(event.target.value)}
              required
              disabled={disabled}
            />
          </div>
        </div>
      </fieldset>

      <div className="form-field">
        <span className="form-label" id="sources-label">
          Sources
        </span>
        <ul className="source-roadmap" aria-labelledby="sources-label">
          {SOURCE_ROADMAP.map((source) => (
            <li
              key={source.code}
              className={
                source.disabled ? "source-roadmap-item is-disabled" : "source-roadmap-item"
              }
            >
              <span className="roadmap-name">{source.name}</span>
              <span className="roadmap-status">{source.status}</span>
              {source.note && <span className="roadmap-note">· {source.note}</span>}
            </li>
          ))}
        </ul>
      </div>

      {localError && (
        <p className="form-error" role="alert">
          {localError}
        </p>
      )}

      <div className="what-you-get">
        <span className="form-label">What you’ll get</span>
        <p>References · Patterns · Opportunities · Ideas · Content briefs</p>
      </div>

      <button type="submit" className="primary-button" disabled={disabled}>
        {disabled ? "Generating report…" : "Generate research report"}
      </button>
    </form>
  );
}
