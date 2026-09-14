"use client";

import { useState } from "react";

import {
  DATE_PRESETS,
  EXAMPLE_QUERIES,
  MARKETS,
  RESEARCH_DEPTHS,
  SOURCE_OPTIONS,
  presetRange,
  todayISODate,
  toISODate,
  type ResearchFormValues,
} from "@/components/ResearchForm";

interface SimpleFormProps {
  onSubmit: (values: ResearchFormValues) => void;
  disabled: boolean;
  initialValues?: Partial<ResearchFormValues>;
  showExamples?: boolean;
}

export function SimpleForm({ onSubmit, disabled, initialValues, showExamples }: SimpleFormProps) {
  const [topic, setTopic] = useState(initialValues?.topic ?? "");
  const [expanded, setExpanded] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const [markets, setMarkets] = useState<string[]>(() =>
    initialValues?.markets?.length ? [...initialValues.markets] : ["SG"],
  );
  const [source, setSource] = useState<string>(() =>
    initialValues?.sources?.[0] === "facebook" ? "facebook" : "youtube",
  );
  const [resultLimit, setResultLimit] = useState<number>(() => {
    const value = initialValues?.result_limit;
    return value !== undefined && RESEARCH_DEPTHS.some((d) => d.value === value) ? value : 50;
  });
  const [facebookPageId, setFacebookPageId] = useState(initialValues?.facebook_page_id ?? "");

  const [preset, setPreset] = useState<string>("custom");
  const [dateFrom, setDateFrom] = useState<string>(initialValues?.date_from ?? "");
  const [dateTo, setDateTo] = useState<string>(initialValues?.date_to ?? "");
  const [maxDate, setMaxDate] = useState<string>("");

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

  function toggleMarket(code: string) {
    setMarkets((current) =>
      current.includes(code) ? current.filter((m) => m !== code) : [...current, code],
    );
  }

  function orderedMarkets(): string[] {
    return MARKETS.map((entry) => entry.code).filter((code) => markets.includes(code));
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
    if (markets.length === 0) {
      setLocalError("Select at least one market.");
      return;
    }
    if (source === "facebook" && !facebookPageId.trim()) {
      setLocalError("Enter the Facebook Page ID to research.");
      return;
    }
    setLocalError(null);

    const values: ResearchFormValues = {
      topic: topic.trim(),
      markets: orderedMarkets(),
      sources: source === "facebook" ? ["facebook"] : ["youtube"],
      result_limit: resultLimit,
      facebook_page_id: source === "facebook" ? facebookPageId.trim() : undefined,
    };
    // Only send an explicit window when the user actually set one; otherwise
    // omit the fields so the M35A adapter applies its default last-30-days
    // window. Sending empty strings would fail date parsing.
    if (dateFrom && dateTo) {
      values.date_from = dateFrom;
      values.date_to = dateTo;
    }
    onSubmit(values);
  }

  return (
    <form className="research-form simple-research-form" onSubmit={handleSubmit}>
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

      <button type="submit" className="primary-button" disabled={disabled}>
        {disabled ? "Generating report…" : "Generate research report"}
      </button>

      {localError && (
        <p className="form-error" role="alert">
          {localError}
        </p>
      )}

      <div className="advanced-options">
        <button
          type="button"
          className="advanced-toggle"
          onClick={() => setExpanded((current) => !current)}
          disabled={disabled}
          aria-expanded={expanded}
        >
          Advanced options
          <span className="toggle-icon" aria-hidden="true">
            {expanded ? "▲" : "▼"}
          </span>
        </button>

        {expanded && (
          <div className="advanced-content">
            <div className="form-row">
              <fieldset className="form-field source-fieldset market-fieldset">
                <legend>Markets</legend>
                <div className="source-options market-options">
                  {MARKETS.map((entry) => (
                    <label
                      key={entry.code}
                      className={[
                        "source-option",
                        markets.includes(entry.code) ? "is-selected" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      <input
                        type="checkbox"
                        name="markets"
                        value={entry.code}
                        checked={markets.includes(entry.code)}
                        onChange={() => toggleMarket(entry.code)}
                        disabled={disabled}
                      />
                      <span className="source-name">{entry.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="form-field">
                <label htmlFor="simple-depth">Research depth</label>
                <select
                  id="simple-depth"
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
              <p className="date-help">
                Presets update both dates. Editing either date switches to Custom.
                Leave blank to use the default last-30-days window.
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

            <fieldset className="source-fieldset">
              <legend>Source</legend>
              <div className="source-options">
                {SOURCE_OPTIONS.map((option) => (
                  <label
                    key={option.code}
                    className={[
                      "source-option",
                      source === option.code ? "is-selected" : "",
                      option.disabled ? "is-disabled" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    <input
                      type="radio"
                      name="source"
                      value={option.code}
                      checked={source === option.code}
                      onChange={(event) => setSource(event.target.value)}
                      disabled={option.disabled || disabled}
                    />
                    <span className="source-name">{option.name}</span>
                    {option.note && <span className="source-note">{option.note}</span>}
                  </label>
                ))}
              </div>
            </fieldset>

            {source === "facebook" && (
              <div className="form-field page-id-field">
                <label htmlFor="simple-facebook-page-id">Facebook Page ID</label>
                <input
                  id="simple-facebook-page-id"
                  type="text"
                  value={facebookPageId}
                  onChange={(event) => setFacebookPageId(event.target.value)}
                  placeholder="123456789"
                  disabled={disabled}
                />
                <p className="date-help">
                  Enter a public Facebook Page ID. Trendora’s server must have
                  approved Meta access configured.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </form>
  );
}
