# Implement the isolated Personal CRM core

This living plan follows `.agent/PLANS.md`. Changes are restricted to `personal-crm/` on `codex/personal-crm-core`, based on the fetched `codex/personal-crm-bootstrap`. The existing bot, databases and deployment remain separate.

## Purpose / Big Picture

An owner can save a synthetic incoming message, create a task or review a mail proposal, deliver a reminder through a fake transport, and explicitly close the task. Sources, history and pending deliveries survive process restart in PostgreSQL. No real Telegram, mail or OpenAI accounts are accessed.

## Progress

- [x] (2026-10-13) Verified clean branch `work`; fetched bootstrap and created separate implementation branch. Read task, instructions and all supplied documents.
- [x] (2026-10-13) Inspected legacy configuration, SQLite schema, input routing, reminder service, timezone helpers and existing tests. Docker daemon is available.
- [x] (2026-10-13) Recorded LEGACY_AUDIT; implemented package, closed-by-default owner/connector authentication and Alembic migrations.
- [x] (2026-10-13) Implemented source-first commits, immutable revisions, technical/account deduplication, retryable interpretation, version-bound proposals and explicit commands with atomic history/jobs.
- [x] (2026-10-13) Implemented PostgreSQL leased jobs, SKIP LOCKED/fencing, crash recovery, durable attempts, bounded retries/uncertainty and cap/gap/single-repeat policy; simple daily digest.
- [x] (2026-10-13) Ran 42 tests on PostgreSQL (5.06s, one deprecation warning), migrations down/up/check, 133 legacy tests, two consecutive demos, Docker build, Compose HTTP/background smoke and actual PostgreSQL restart/readback. Recorded partial/unrun acceptance scope.
- [x] (2026-10-13) Confirmed changes confined to personal-crm, no unintended tracked edits; secret scan and diff check passed. Committed implementation and pushed codex/personal-crm-core. GitHub PR API returned 403, so PR creation remains externally blocked; no force push or merge performed.

- [x] (2026-10-13) Added explicit plan/defer/resume/cancel/focus commands, separate postponement counter and additive migration 9b0fd1794927; preserved old core records in a real migration test.
- [x] (2026-10-13) Added GET /overview and protected history/guidance/delivery inspection; ranked main three, retained all deadlines and rotated two forgotten tasks using presentation/discussion times.
- [x] (2026-10-13) Added one-time overdue/obstacle events, digest fallback, configurable missed-job batching, explicit reschedule invalidation and conservative recovery of cancelled jobs with unfinished attempts.
- [x] (2026-10-13) Validated 69 PostgreSQL tests (11.39s, one known deprecation warning), 133 legacy tests (1.11s), 28-day simulation, core demo and updated Compose HTTP smoke; updated README/ACCEPTANCE.
- [ ] Save continuation commit and verify GitHub branch publication.

## Surprises & Discoveries

Legacy `bot/app.py` and datetime utility modules are compatibility exports. Actual orchestration is in `bot/application.py`, handlers in `bot/handlers/messages.py`, and time functions in `bot/utils/date_utils.py`. SQLite stores reminder dates but APScheduler jobs live in process memory. Docker Server 28.4.0 is available; a dedicated PostgreSQL container can validate concurrency without touching legacy data.

## Decision Log

Use synchronous SQLAlchemy transactions with psycopg and Alembic. PostgreSQL is mandatory, including tests. Owner identity comes from configured credentials, never request bodies. Model proposals never confer command authority. Explicit owner HTTP/CLI commands authorize changes. Fake interpretation uses reviewed synthetic fixtures, not a pretend Russian language parser. Unknown timezone prevents calendar-policy notifications. Real AI adapter will remain absent/disabled in this first core; implementing billing and provider compatibility without agreed prices is outside the required fake workflow.

## Outcomes & Retrospective

M0–M4 delivered the first fake-only end-to-end core. A synthetic owner source commits before interpretation; technical duplicate does not repeat interpretation or task creation; a separate worker records delivery; explicit close cancels the repeat; a mail proposal creates a task only after confirmation. All 42 CRM checks passed on PostgreSQL, including real transaction failure/rollback and concurrent worker claims. The legacy suite passed 133. Docker/Compose startup and HTTP smoke passed, and an actual database restart preserved task, delivery attempt and cancelled repeat. The continuation also delivered explicit execution planning/defer/resume/cancel/focus, rotating and ranked daily overview, single overdue/obstacle guidance and delayed-exact-job consolidation. Full React, real channels, AI/budget evaluation, mail synchronization/retention, recurrence/steps/adaptation, early-plan suggestions, backup/restore and production migration remain later milestones. No production readiness is claimed.

## Context and Orientation

`personal-crm/CODEX_TASK.md` defines M0–M4. New code lives under `personal-crm/src/personal_crm/`. PostgreSQL contains owner profiles, source identities and immutable source versions, tasks/expectations, version-bound proposals, append-only history, reminders, jobs and delivery attempts. A lease is a short reservation of a queue job; its expiry allows recovery after a stopped worker. An uncertain delivery means a transport may have sent a message but cannot confirm it; it must not be silently retried.

## Plan of Work

M0 records the audit in `docs/LEGACY_AUDIT.md`. M1 introduces packaging, fixed dependencies, server settings, owner checks, FastAPI endpoints, Alembic schema and isolated Compose services. M2 implements services that commit incoming source before interpretation and atomically change tasks, history and jobs. The worker claims jobs using PostgreSQL row locks, records attempts before transport and checks task/reminder versions before sending. M3 adds controlled fixtures and a demo CLI showing owner input, mail proposal confirmation, restart/readback and cancellation of a repeat. M4 tests failure paths, concurrency and policy using an isolated PostgreSQL database; updates acceptance evidence and pushes only the implementation branch.

## Concrete Steps

Work from `/workspace/TG_bot/personal-crm`. Create an isolated `.venv`, install locked dependencies, start a dedicated PostgreSQL service, set `CRM_DATABASE_URL`, run `alembic upgrade head`, `pytest`, and `python -m personal_crm.demo`. The verified sequence from `/workspace/TG_bot/personal-crm` is:

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.lock
    .venv/bin/python -m pip install --no-deps --no-build-isolation -e .
    docker run --name personal-crm-test-pg -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER=crm_test -e POSTGRES_DB=personal_crm_test -p 127.0.0.1:55432:5432 -d postgres:16.10
    export CRM_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test
    .venv/bin/alembic upgrade head
    CRM_TEST_DATABASE_URL="$CRM_DATABASE_URL" .venv/bin/python -m pytest -q
    .venv/bin/python -m personal_crm.demo
    .venv/bin/python -m personal_crm.simulation

Reuse the named container if it exists; wait for `docker exec personal-crm-test-pg pg_isready -U crm_test` before connecting. This trust-mode server is disposable and only exposed on loopback. The test runner requires an opt-in test URL/database name and resets its schema. Current expected test output is `69 passed, 1 warning`; the warning is a Starlette/AnyIO deprecation. Demo output confirms source persistence, one fake delivery, duplicate protection, repeat cancellation and mail confirmation, with zero external calls. Demo uses a unique synthetic profile and launches separate readback and worker processes.

For containers, run `.venv/bin/python scripts/prepare_wheels.py`, then `docker build --build-context crm_wheels=.runtime/wheels -t personal-crm:dev .`. Configure local credentials in ignored `.env`: CRM_DB_PASSWORD and the matching CRM_DATABASE_URL for user crm, host crm-db, database personal_crm; CRM_OWNER_ID, CRM_OWNER_TOKEN, CRM_FAKE_MAIL_TOKEN, and an explicitly synthetic IANA timezone. `docker compose --env-file .env up -d` starts database/migrations/API/worker. `scripts/smoke_http.py` uses the same owner credentials and a host PostgreSQL URL at 127.0.0.1:55433 to verify actual HTTP/background delivery and close/cancel. Generated test credentials never belong in committed files. Complete operational examples are in README, with all secret placeholders empty.

## Validation and Acceptance

Tests must demonstrate source persistence across parse failures, technical deduplication, separate manual forwards, mail proposals, object access checks, stale confirmations, reminder changes without deadline changes, restart and lease recovery, worker concurrency, close-before-send, uncertain delivery and limits with controlled UTC clocks. Verify API through HTTP requests, migrations and a real PostgreSQL server. Existing bot tests serve as regression evidence, without starting its real polling process. Real model quality is untested.

## Idempotence and Recovery

Alembic upgrades can be rerun. Demo IDs are unique per run, so no truncation of user databases is needed. Tests require an explicitly named disposable test database. Reset only that test schema. Never use production connection strings. Workers cap retries and stop automatic retries after uncertain send outcomes. Only stop services started for this task. Never reset or overwrite unrelated changes.

## Artifacts and Notes

Initial Git status was clean. Bootstrap added only documentation under `personal-crm/`. Initial core validation: legacy `133 passed in 1.37s`, CRM `42 passed, 1 warning in 5.06s`. Current continuation validation: legacy `133 passed in 1.11s`, CRM `69 passed, 1 warning in 11.39s`. Two consecutive demos returned all assertions true and fake_delivery_attempts=1. Actual Compose smoke returned `HTTP smoke passed: readiness, owner auth, source, reminder, background fake delivery, close/cancel`. PostgreSQL restart returned `Actual PostgreSQL restart: task, delivery attempt and cancelled repeat persisted`. Detailed requirement/decision/test mappings are in docs/ACCEPTANCE.md.

## Interfaces and Dependencies

FastAPI provides an owner-authenticated demonstration API. SQLAlchemy and psycopg implement PostgreSQL transactions; Alembic owns schema changes. Pydantic validates a restricted interpretation schema. `Interpreter` and `Transport` protocols have fake implementations only. `CRMService` handles source intake, processing and commands; `Worker` handles reservation and delivery. `accompaniment.prepare` recovers ambiguous attempts, returns explicitly deferred tasks, records overdue events and batches stale exact jobs. `overview` ranks and describes obligations without changing them; `record_presentation` updates successful exposure and durable one-time event outcomes. `Guidance` is advisory, never an executable model action. Docker Compose runs separate database, API and worker services with a dedicated volume.

Revision 2026-10-13: established actual inspection evidence and implementation boundaries before coding.

Revision 2026-10-13, implementation: replaced provisional progress with delivered modules and executed tests. Owner commands and all sends share an owner-row lock so notification budget reservations and state changes serialize; attempts commit before side effects, and unresolved attempts recover as uncertain rather than silently resend. All real provider adapters remain disabled because the task authorizes only fake adapters. Relative dates not covered by a fixture clarify rather than fabricate a deadline.

Revision 2026-10-13, container validation: Docker could not resolve PyPI/proxy hostnames, including with host networking. The supported correction downloads public pinned wheels with normal TLS, verifies checksums inside an offline build, and uses a separate build context so artifacts stay ignored. Non-root startup initially failed because checkout file permissions were private; the image now explicitly grants read/traverse permissions only to copied application files. The migration, API and worker then started successfully. The worker handles transient PostgreSQL errors without exposing connection-string diagnostics. Actual PostgreSQL restart and repeated HTTP smoke demonstrated reconnection and persisted state. At that first-core milestone, long-outage consolidation was still unimplemented and T21 was partial. The continuation below implements and verifies it; fake transport remains the only active transport.

Revision 2026-10-13, handoff: Git push of the implementation branch succeeded. GitHub GraphQL returned Forbidden when creating the PR; native Git write access does not establish API permission. The branch is reviewable on GitHub; no token was requested or extracted to bypass this scope. Final documentation records verified setup and unresolved release/integration scope.

Revision 2026-10-13, continuation scope: user asked to continue without changing prior fake-only authorization. The next milestone implements deterministic accompaniment before real channel work. Planning and reminder postponement remain separate. A later execution date counts as a postponement only after an existing plan; reminder moves and silence do not count. Every third such explicit postponement creates one obstacle question, not an autonomous state change. Deferred tasks return on an explicit calendar date in the configured profile timezone. Unknown timezone blocks calendar operations.

The daily overview preserves all dated obligations in the full response, limits its main list to three and rotates up to two undated tasks using last successful presentation and last owner discussion. Presentation is not evidence of reading. Overdue events use a durable identity derived from the agreed deadline and are reported once either as an initiative or through the digest. Old exact reminders more than a configurable one-hour grace period late will be retained as missed jobs and collected in one guidance report; task/deadline/history remain intact, and uncertain attempts cannot be collapsed into definite misses. No public NLP quality or production readiness is claimed.

Revision 2026-10-13, accompaniment verified: full current suite is 69 passed in 11.39s with one existing Starlette/AnyIO warning. The 28-day PostgreSQL simulation returned 28 distinct daily digests, 13 undated tasks presented, one overdue event, one obstacle question, three missed jobs consolidated, no automatic completions and no external calls. Core demo passed again. The rebuilt non-root Compose applied the additive migration to existing synthetic data and passed HTTP readiness/auth/source/reminder/fake delivery/close plus plan/overview/history. Legacy suite passed 133 and secret scan passed. No production or real-account operations were performed.

The migration spike exposed two actual issues: ambiguous ORM joins when selecting multiple entities and unnamed/dropped constraints in the generated downgrade. Explicit join predicates and named constraints with dependency-ordered drops fixed them. Migration down/up/check and preservation of old core rows now pass. History rejection proves the third-postponement count, obstacle guidance and job roll back together.

Decision: guidance IDs and membership of a message are stored in attempt payloads without copying private text to application logs. Pending or uncertain membership reserves one-time guidance against concurrent/duplicate summary delivery. Lost intents on cancelled jobs become unknown rather than remain pending forever. Rendering occurs again immediately before fake transport so intervening owner edits do not send stale text, and committed delivery timestamps use the actual send day across profile midnight. No event automatically completes or replans an obligation. Unknown provider outcome does not prove receipt and does not get an automatic warning resend.

Decision: three explicit later execution dates trigger an obstacle question; reminder time changes, initial planning, silence, same date and earlier dates do not. Every further group of three postponements may trigger a new question. Dated tasks remain in the full daily overview while main is capped at three; forgotten rotation uses last successful presentation and last owner discussion, not assumed reading. Automatic return is allowed only by the explicitly stored return date and IANA profile timezone. A one-hour grace is a stored profile setting for delayed exact jobs; detailed missed job IDs stay durable even if a later owner command makes the report inapplicable.

The next incomplete milestones remain synthetic/offline channel input and bound conversational confirmations, proposed substeps/regular instances, real mail/provider configuration only when authorized, React, encrypted restore and copy-only legacy import. Real paid AI requires a separately implemented and validated reservation/budget gateway; fake fixture quality is not evidence of Russian-language interpretation. This continuation completes deterministic accompaniment, not the entire production release.
