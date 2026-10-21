# Planner builder handoff

## Model recommendation

Trial Muse Spark 1.3 Contributor Free first, using xhigh only if the installed OpenCode/provider combination actually supports it. This is a provisional continuity choice from the planning conversation, not a measured claim that Muse outperforms MiMo or DeepSeek on Trendora. Evaluate one bounded milestone before keeping the choice.

MiMo-V2.6-Flash Free is the alternative if Muse is unavailable or repeatedly fails the task gate. Do not rotate builders mid-milestone without handing over the current diff and evidence.

DeepSeek V4.1 Flash is currently a paid option on OpenCode Zen, so do not select it under a zero-cost constraint without explicit budget approval. OpenCode lists it at $0.30 input and $1.20 output per million tokens, with cached input priced separately. Prices and free availability can change.

OpenCode documents that Muse Contributor prompts/completions may be used for Meta model training and that MiMo free data may be used to improve its model. This applies to repository content sent to a coding agent too. Do not send credentials, actual private drafts or confidential company material. Lex must be comfortable sharing the code context under the selected provider's policy.

Sources checked September 25, 2026:

- [OpenCode Zen models, pricing and privacy](https://opencode.ai/docs/zen/)
- [DeepSeek release changelog](https://api-docs.deepseek.com/updates/)

No model was configured or started by creating this handoff. The coding model selection does not change Trendora's runtime provider.

## First prompt: read-only preflight

Paste the following into the selected builder. This prompt intentionally does not authorize implementation before the written design has been reviewed.

```text
You are reviewing the Trendora repository before implementing its shared content planner.
Work in /Users/lex/Projects/trendora.

This first task is read-only. Do not edit files, install packages, run migrations,
start live provider calls, deploy, commit, or change OpenCode/9router configuration.

Read AGENTS.md, web/AGENTS.md, README.md, pyproject.toml, web/package.json, and:
docs/superpowers/specs/2026-09-25-shared-content-planner-design.md

Read the relevant source files and callers yourself. The spec names current seams
but is not a substitute for tracing the actual code. Check git status first and
preserve every existing user change. Do not read .env or other credential files.

The product is a private shared content planner for two marketing colleagues:
Lex is Admin + Editor; the colleague is Editor + Approver. Admin is not automatic
approval authority. Approval is optional per post. Manual planning/editing must
work with all AI providers unavailable. Posts are editable, reports are snapshots.

Read the complete design, especially approval invalidation, prevention of review
bypass, publication without approval, source provenance, and concurrent updates.
Do not add company-wide management, auto-publishing, uploads, analytics or billing.

Concentrate on P0, the safe test foundation, as the proposed first implementation
milestone. Inspect all callers of persistence and the integration engine fixtures.
Confirm that unit tests cannot contact real providers/databases before running them.
Use mocks and explicit network/database guards; disable bytecode/cache output for
this read-only task. Do not run integration tests against any actual database.

Return:
1. Confirmed code seams and any design contradictions, with exact file/line references.
2. The smallest proposed P0 file list and tests, including how to prove an explicit
   test URL selects the engine without making a connection.
3. Any material blocker. Do not invent hosting or authentication settings.
4. Commands actually run, results, and any safety guards that blocked attempted I/O.

Stop after this report. The main reviewer will review the design and issue a
bounded implementation prompt. Do not implement the entire roadmap autonomously.
```

## Implementation handoff rule

After Lex reviews the written design, the main planner writes a code-ready task plan
with file paths, interfaces, runnable regression tests, commands and stop conditions.
Lex reviews that plan before the builder implements P0. Later milestones receive
separate bounded prompts, not one instruction to build the entire planner.

For every implementation milestone:

1. Builder reads the approved spec/task, checks the dirty tree, and traces callers.
2. Builder writes a failing regression check, implements the smallest scoped change,
   and runs that check plus the relevant existing checks.
3. Builder returns changed files, command results, unresolved risks and remaining work.
4. Main reviewer inspects the actual diff, independently reruns relevant checks, and
   verifies permission and data-loss cases. Builder assertions alone do not pass a gate.
5. Stop before the next milestone, external changes, or an expansion of scope.

Judge the trial by passing acceptance checks, scope discipline, absence of unrelated
edits, test quality, and correction effort. Do not judge it by model branding or the
reasoning-effort label. Do not claim benchmarks or speed comparisons not measured here.

## First implementation boundary

P0 may change test isolation and dedicated test-engine setup only, after approval.
It must not add planner tables, auth, frontend changes, dependencies or provider logic.
Do not run production migrations. Prove the selected test URL with an engine whose
connection is mocked. The test guard must fail loudly on accidental real I/O, not
silently skip tests or mask production persistence defects.

Suggested review targets, to verify against current code:

- tests/conftest.py
- tests/unit/test_research_report_api.py and every unit caller of the report endpoint
- tests/integration/conftest.py and every integration fixture calling get_engine
- src/trendora/db/session.py, read to understand engine caching and caller behavior

No runtime behavior should need to change just to make tests safe. If that assumption
is wrong, explain why before broadening P0.
