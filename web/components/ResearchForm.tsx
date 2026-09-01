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

export const RESULT_LIMITS = [10, 20, 50, 100];

export interface ResearchFormValues {
  topic: string;
  market: string;
  date_from: string;
  date_to: string;
  sources: string[];
  result_limit: number;
}

interface ResearchFormProps {
  onSubmit: (values: ResearchFormValues) => void;
  disabled: boolean;
}

export function ResearchForm({ onSubmit, disabled }: ResearchFormProps) {
  const [topic, setTopic] = useState("");
  const [market, setMarket] = useState("SG");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [resultLimit, setResultLimit] = useState(20);
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setLocalError("Start date must not be after end date.");
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
      <div className="form-field">
        <label htmlFor="topic">Topic</label>
        <input
          id="topic"
          type="text"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="e.g. AI education"
          required
          disabled={disabled}
        />
      </div>

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
          <label htmlFor="result-limit">Result limit</label>
          <select
            id="result-limit"
            value={resultLimit}
            onChange={(event) => setResultLimit(Number(event.target.value))}
            disabled={disabled}
          >
            {RESULT_LIMITS.map((limit) => (
              <option key={limit} value={limit}>
                {limit}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="date-from">From</label>
          <input
            id="date-from"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
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
            onChange={(event) => setDateTo(event.target.value)}
            required
            disabled={disabled}
          />
        </div>
      </div>

      <div className="form-field">
        <span className="form-label" id="sources-label">
          Sources
        </span>
        <div className="source-chip" role="group" aria-labelledby="sources-label">
          <span className="source-chip-name">YouTube</span>
          <span className="source-chip-note">
            the only available research source
          </span>
        </div>
      </div>

      {localError && (
        <p className="form-error" role="alert">
          {localError}
        </p>
      )}

      <button type="submit" className="primary-button" disabled={disabled}>
        Research
      </button>
    </form>
  );
}
