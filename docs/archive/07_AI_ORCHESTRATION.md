# 07 — AI orchestration

Status: Phase 0 placeholder. No agents.

## Principle

**Python owns the truth. AI owns the explanation.**

The orchestrator may only receive:

- precomputed KPI tables
- forecast summaries
- anomaly flags
- constrained excerpts the Python layer selected

It must **not** receive:

- unrestricted SQL
- raw database credentials
- a dump of comments/PII
- tools that can mutate production data

## $0 default

AI is optional. If no provider is configured, Streamlit still shows Python analytics.

Provider-agnostic adapter (later):

```text
ExplanationRequest → AIProvider (noop | local | remote) → ExplanationResponse
```

Do not hard-code a paid vendor. Do not make ingestion or KPIs depend on LLM uptime.

## Safety

- Prompt injection: never instruct the model to “follow” text found in comments or titles as commands.
- Log prompt/response IDs next to the analytics run they explain.
- Human-readable disclaimer: explanations are interpretive, not source metrics.

MCPs (GitHub, Postgres, Context7) are **developer** tools. They are not this orchestrator and must not be wired into the production app.
