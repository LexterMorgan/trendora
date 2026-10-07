# 11 — Deployment

Historical deployment outline. Hosting and deployment status are unverified.
Use [DEPLOYMENT.md](DEPLOYMENT.md) for current templates and ordered release operations.

## Target shape

| Environment | Compute | Database |
| --- | --- | --- |
| V1 development | local Python 3.12 venv | existing Supabase PostgreSQL (`https://ymzloduyggkcmapmiics.supabase.co`) |
| Optional local Postgres | same venv | local PostgreSQL (portable; not required for V1) |
| Production | undecided, **must stay $0-feasible** | Supabase PostgreSQL (free tier must be re-verified at deploy time) |

SQLAlchemy + Alembic remain the migration path in both environments.

## $0 infrastructure notes

- Supabase free tier, GitHub, and Google Cloud free quotas can change. Re-verify before go-live.
- Do not adopt paid workers, paid scrapers, or paid LLM hosting as defaults.
- Streamlit Community Cloud or a single small VM may be candidates later; neither is selected.

## Secrets

`.env` locally; platform secrets in production. Never commit `.cursor/mcp.json` with tokens.

## Not started

The repository now contains optional Docker/Render templates and a release
runbook. Target-specific database verification, secret provisioning, cleanup
scheduling and deployed acceptance remain pending in [DEPLOYMENT.md](DEPLOYMENT.md).

## Related

MCP setup for developers: [../PROJECT_PREP.md](../PROJECT_PREP.md) and `.cursor/mcp.json.example`.
