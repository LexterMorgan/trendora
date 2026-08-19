# 00 — Project overview

Status: Product brief still applies. Milestone 1 added the database foundation; see [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md). Connectors and product surfaces are not implemented.

## Product

Trendora is an AI-powered Social Media Intelligence Platform focused on Southeast Asian education, AI, and technology markets.

It will eventually analyze social-media and related public data across Southeast Asia and provide:

- Market intelligence
- Content intelligence
- Campaign analytics
- NLP
- Machine learning
- Time-series forecasting
- Anomaly detection
- AI-powered analysis
- Evidence-based recommendations
- Interactive dashboarding

## Core product question

> What is happening across Southeast Asian education and technology markets, why is it happening, what is likely to happen next, and what should we do next?

## Primary markets

Indonesia, Thailand, Malaysia, Singapore, Vietnam, Philippines.

## Primary domain

AI education, technology education, data science, programming, digital skills, STEM, online learning, scholarships, technology/career education.

## Cost constraint

Designed around a **$0 budget**.

The core system must not depend on paid APIs, paid datasets, paid LLM APIs, paid scraping services, paid databases, or paid infrastructure. Free/open-source options are preferred.

Do not assume an API is free, provides historical data, or provides the metrics we need. Those facts must be verified from official documentation before implementation. See [03_DATA_SOURCES.md](03_DATA_SOURCES.md).

## Technology direction

- Python-first (3.12+)
- PostgreSQL locally in development; Supabase PostgreSQL in production
- SQLAlchemy + Alembic, portable between local Postgres and Supabase
- FastAPI
- Streamlit dashboard (required; do not switch to React/Vite)
- Plotly, Pandas, NumPy
- scikit-learn, statsmodels
- NLP libraries only where justified
- Provider-agnostic AI architecture (optional; analytics must work without a paid LLM)

## Principle

**Python owns the truth. AI owns the explanation.**

Python calculates KPIs, trends, forecasts, anomalies, predictions, and statistical results. AI interprets structured results. The LLM must not receive unrestricted raw database access.

## Current phase

Phase 0: workspace, MCP audit, documentation skeleton, data-source research.

Do not build ingestion, APIs, ML, agents, or the dashboard until Phase 1 is explicitly authorized.
