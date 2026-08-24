# Stabilize and deploy the Telegram personal assistant

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds. Maintain this document in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

The owner should be able to use the Telegram bot every day without losing reminders or personal data. The bot must protect its token, avoid writing private note text into diagnostic logs, deliver one follow-up notification when a reminder is ignored, expose complete button-based management for notes and reminders, survive a VPS restart, and create encrypted off-server backups.

## Progress

- [x] (2026-05-30) Reviewed the current application, database, handlers, tests, Docker files, and logs.
- [x] (2026-05-30) Identified an exposed Telegram token in historical HTTP logs and a missing `.env` exclusion in `.dockerignore`.
- [x] (2026-05-30) Closed future secret leaks, added rotating redacted logs, and purged historical runtime logs.
- [x] (2026-05-30) Applied the configured default timezone to new chat settings.
- [x] (2026-05-30) Added one follow-up reminder ten minutes after an ignored notification.
- [x] (2026-05-30) Added complete button management, pagination, and interactive search results.
- [x] (2026-05-30) Added Linux VPS deployment, health monitoring, and encrypted S3-compatible backup tooling.
- [x] (2026-05-30) Added a local production preflight for SQLite integrity, online backup, and Docker Compose requirements.
- [x] (2026-05-30) Added callback regression tests for archive, restore, delete, pagination, and settings-based JSON import/export.
- [x] (2026-05-30) Redacted free-form callback segments so legacy search callbacks cannot leak query text.
- [x] (2026-05-30) Added pre-validation and size limits for JSON imports so malformed backups fail before modifying SQLite.
- [x] (2026-05-30) Unified day-plan job synchronization so disabled settings remove stale scheduled tasks.
- [x] (2026-05-30) Added schema-aware SQLite health checks and a one-command restic restore verification script.
- [x] (2026-05-30) Fixed overdue recurring completion and tomorrow postponement so both always move reminders into the future.
- [x] (2026-05-30) Ran local validation: `54 passed`, secret scan passed, production preflight passed, healthcheck passed, and shell syntax checks passed.
- [x] (2026-05-31) Made the owner allowlist mandatory and fail-closed so a missing environment variable cannot expose the personal bot publicly.
- [x] (2026-05-31) Removed raw Telegram user IDs, chat IDs, and exact reminder timestamps from interaction logs and JSON export metadata.
- [x] (2026-05-31) Prevented silent JSON export truncation, made statistics count all records, and sanitized alert-tool network failures.
- [x] (2026-05-31) Ran local validation: `59 passed`, secret scan passed, production preflight passed, healthcheck passed, shell syntax checks passed, and Git dry-run excluded runtime secrets and data.
- [x] (2026-05-31) Added explicit environment validation for logging limits, timezone range, owner IDs, and separate runtime log paths.
- [x] (2026-05-31) Made JSON import atomic in one SQLite transaction and rejected malformed records instead of silently skipping them.
- [x] (2026-05-31) Ran local validation: `66 passed`, secret scan passed, production preflight passed, healthcheck passed, shell syntax checks passed, runtime logs contained no token-shaped values, and Git dry-run excluded runtime secrets and data.
- [x] (2026-05-31) Hardened the Docker Compose service with a read-only root filesystem, dropped Linux capabilities, no-new-privileges, an init process, and a writable temporary filesystem.
- [x] (2026-05-31) Added `deploy/preflight.sh` to validate VPS commands, configured secret files, Compose rendering, data-directory access, and an existing database without printing secrets.
- [x] (2026-05-31) Replaced ambiguous numeric VPS template IDs with explicit placeholders.
- [x] (2026-05-31) Ran local validation: `67 passed`, secret scan passed, production preflight passed, healthcheck passed, all four shell syntax checks passed, runtime logs contained no token-shaped values, and Git dry-run excluded runtime secrets and data.
- [x] (2026-05-31) Fixed additive SQLite migration order so legacy schemas gain new columns before indexes reference them.
- [x] (2026-05-31) Made application and CLI SQLite backup snapshots atomic: a verified temporary snapshot replaces the previous backup only after `PRAGMA quick_check`.
- [x] (2026-05-31) Updated VPS upgrade documentation to create an external backup before rollout and run preflight plus an in-container healthcheck.
- [x] (2026-05-31) Ran local validation: `71 passed`, compileall passed, secret scan passed, production preflight passed, healthcheck passed, all four shell syntax checks passed, runtime logs contained no token-shaped values, and Git dry-run excluded runtime secrets and data.
- [x] (2026-05-31) Fixed VPS preflight to validate container UID `10001` ownership instead of incorrectly requiring host-user write access to mounted data directories.
- [x] (2026-05-31) Moved the host health-monitor state file outside the container-owned `data` directory and ignored it in Git.
- [x] (2026-05-31) Ran local validation: `72 passed`, compileall passed, secret scan passed, production preflight passed, healthcheck passed, all four shell syntax checks passed, runtime logs contained no token-shaped values, and Git dry-run excluded runtime secrets and data.
- [ ] Owner action: rotate the exposed bot token through BotFather and update local `.env` before restarting the bot.
- [ ] Owner action: deploy on the Linux VPS with real S3-compatible restic credentials and verify a production restore.

## Surprises & Discoveries

- Observation: `httpx` INFO logging records the full Telegram Bot API URL, which includes the token.
  Evidence: historical `logs/bot.log` entries contain requests to the Bot API.
- Observation: pytest temporary directories under the OneDrive workspace fail with `PermissionError` during setup and cleanup.
  Evidence: `.venv\Scripts\python.exe -m pytest --basetemp=.tmp\pytest-roadmap` fails with Windows error 5.
- Observation: the repository directory was not initialized as a Git repository when implementation started.
  Evidence: `git status --short --branch` returned `fatal: not a git repository`.
- Observation: Docker and restic are not installed in the local Windows environment.
  Evidence: `where.exe docker` and `where.exe restic` found no executables, so production container and S3 integration checks require the VPS.
- Observation: the Snyk MCP scan could not complete because authentication closed the MCP transport.
  Evidence: `snyk_code_scan` requested authentication and `snyk_auth` returned `Transport closed`.
- Observation: `.gitignore` initially excluded the intended tracked `.env.vps.example` template together with real `.env.*` files.
  Evidence: `git ls-files --others --exclude-standard` omitted the template until an explicit `!.env.vps.example` exception was added.
- Observation: standalone SQLite utility connections must be closed explicitly on Windows.
  Evidence: preflight snapshot cleanup failed with `WinError 32` until utility connections used `contextlib.closing`.
- Observation: changing a disabled day-plan time scheduled a repeating job, and importing disabled settings did not remove an existing job.
  Evidence: the message handler called `schedule_dayplan` directly instead of synchronizing jobs from persisted settings.
- Observation: completing or postponing an old overdue reminder could schedule its next notification in the past.
  Evidence: repeat completion advanced only one interval, while tomorrow postponement added one day to the old reminder timestamp.
- Observation: `BOT_ALLOWED_USER_IDS` defaulted to an empty set, and an empty set allowed every Telegram user.
  Evidence: `BotApp.is_user_allowed` returned `True` before checking a user whenever no IDs were configured.
- Observation: JSON export listed at most 5,000 records per bucket without warning.
  Evidence: `build_export_payload` queried each active and archived collection with `limit=5000`.
- Observation: JSON import pre-validation prevented known malformed payloads, but successful records still committed one by one.
  Evidence: `import_payload` called database methods that each opened and committed a separate SQLite connection.
- Observation: the initial Compose service ran as a non-root user but still inherited the default writable root filesystem and Linux capability set.
  Evidence: `docker-compose.yml` had no `read_only`, `cap_drop`, or `security_opt` entries.
- Observation: legacy SQLite schemas could fail during initialization before additive migrations ran.
  Evidence: `Database.init()` created indexes referencing `is_archived` and `done_at` before `_migrate_legacy_columns()` added those columns.
- Observation: a failed SQLite online backup could overwrite the previous local snapshot directly.
  Evidence: both `Database.backup_to()` and `tools/sqlite_online_backup.py` connected the final destination before validating the completed snapshot.
- Observation: the documented VPS ownership setup made mounted data directories writable by container UID `10001`, but host scripts still assumed host-user write access inside `data`.
  Evidence: `deploy/preflight.sh` checked `[[ -w "$ROOT_DIR/data" ]]`, and `deploy/check_bot_health.sh` stored `monitor.status` below that container-owned directory.

## Decision Log

- Decision: Keep SQLite and make only additive schema-compatible changes.
  Rationale: the existing bot already stores the required personal data and must preserve the live database.
  Date/Author: 2026-05-30 / Codex
- Decision: Log interaction metadata only, without note text, reminder text, filenames, voice file identifiers, or transcription text.
  Rationale: the interaction journal is for UX analysis, not a second store of personal content.
  Date/Author: 2026-05-30 / Codex
- Decision: Use a single retry job named `retry10:<reminder_id>`.
  Rationale: one follow-up notification is visible enough without creating repeated spam.
  Date/Author: 2026-05-30 / Codex
- Decision: Deploy with Docker Compose on a Linux VPS and use `restic` for encrypted S3-compatible backups.
  Rationale: this keeps the SQLite volume explicit and makes off-server backup restoration testable.
  Date/Author: 2026-05-30 / Codex
- Decision: Validate and normalize an entire JSON import before writing any imported records.
  Rationale: a malformed backup must not leave a partially updated personal database.
  Date/Author: 2026-05-30 / Codex
- Decision: Require at least one owner ID at application build time.
  Rationale: this is a personal bot, so startup failure is safer than accidentally accepting messages from strangers.
  Date/Author: 2026-05-31 / Codex
- Decision: Apply an imported backup within one SQLite transaction.
  Rationale: a disk or database error midway through import must roll back notes, reminders, and imported settings together.
  Date/Author: 2026-05-31 / Codex
- Decision: Run the VPS container with a read-only root filesystem and no Linux capabilities.
  Rationale: the bot only needs outbound network access and its mounted `/data` directory, so broader container privileges are unnecessary.
  Date/Author: 2026-05-31 / Codex
- Decision: Replace backup snapshots atomically only after a SQLite integrity check.
  Rationale: a failed backup attempt must leave the previous verified local snapshot available for restic and manual recovery.
  Date/Author: 2026-05-31 / Codex
- Decision: Keep host monitoring state outside the container-owned persistent data mount.
  Rationale: container SQLite ownership and host cron monitoring are separate concerns and should not require shared write permissions.
  Date/Author: 2026-05-31 / Codex

## Outcomes & Retrospective

Implemented the production-oriented assistant update. Future logs redact Telegram token-shaped values and omit personal text. The bot now applies the configured default timezone, schedules one ten-minute reminder retry, offers full button management with pages and interactive search, and includes VPS deployment, monitoring, and encrypted restic backup tooling.

Local validation passed with `72 passed`, a clean compileall run, a clean secret scan, a successful production preflight, a schema-aware SQLite healthcheck, successful `bash -n` validation for all VPS scripts, runtime logs without token-shaped values, and a Git dry-run that excluded runtime secrets and data. JSON imports now validate first and commit notes, reminders, and settings atomically. JSON exports no longer include a chat ID or silently truncate oversized data sets. Day-plan scheduling follows persisted enabled settings consistently. Old overdue reminders now move to a future occurrence when completed or postponed. Startup now requires an explicit owner allowlist, validates important environment values, and interaction logs contain only anonymized UX metadata. Legacy SQLite schemas migrate before new indexes are created, and backup snapshots replace their previous file atomically only after an integrity check. The Compose service uses minimal Linux privileges, `deploy/preflight.sh` validates container UID ownership without exposing secrets, and host monitoring state stays outside the container-owned data mount. Docker Compose startup, real S3 backup, restore, and token rotation remain owner-operated production steps because Docker, restic, BotFather access, and S3 credentials are not available in the local environment.

## Context and Orientation

`main.py` loads settings, configures logging, builds the Telegram application, and starts long polling. `bot/application.py` registers Telegram handlers and scheduled jobs. `bot/db.py` owns SQLite access. `bot/handlers/callbacks.py`, `bot/handlers/messages.py`, and `bot/views.py` implement button and text interaction flows. The existing `capture_text` function remains the shared text ingestion entry point.

The SQLite database is a live local file and must never be reset. Migrations must be additive. Voice transcription and the future workout journal are intentionally outside this execution plan.

## Plan of Work

First, replace unbounded logging with rotating files, redact token-shaped values, suppress verbose HTTP client logs, remove content from the interaction journal, exclude local environment files from Git and Docker contexts, and purge historical logs after the new behavior is in place.

Second, pass the configured default timezone into `Database`, add a single ten-minute delivery retry job, preserve pending reminders across restarts, and add regression tests.

Third, add offset-based database listing, page controls for active and archived records, interactive search result buttons, reminder archive and restore controls, and confirmed deletion. Show immediate edit and cancellation buttons after a reminder is created.

Fourth, add Docker Compose, a database healthcheck, SQLite online backup tooling, restic orchestration scripts, alert scripts, cron examples, and deployment documentation. Initialize a local Git repository after secret cleanup; creating a hosted private remote still requires the owner's account and target repository choice.

## Concrete Steps

Run commands from the repository root:

    .venv\Scripts\python.exe tools\run_tests.py -q
    .venv\Scripts\python.exe tools\check_no_secrets.py
    .venv\Scripts\python.exe tools\production_preflight.py
    .venv\Scripts\python.exe -m compileall -q main.py bot tools tests

On a Linux VPS:

    cp .env.vps.example .env.vps
    deploy/preflight.sh
    docker compose up -d --build
    docker compose ps
    deploy/backup_to_s3.sh
    deploy/verify_restore.sh

## Validation and Acceptance

The full Python test suite must pass in a writable system temporary directory. A secret scan must find no token-shaped value outside ignored local runtime files. New logs must omit Bot API tokens and personal record text.

After starting the bot, a text note must save immediately. A natural-language reminder must show `Изменить`, `Отменить`, and `В меню`. If the owner ignores a fired reminder, the owner must receive exactly one follow-up after ten minutes. Opening notes, reminders, archives, and search results must allow navigation to records beyond the first page.

On the VPS, `docker compose up -d --build` must start the bot with `/data/notes.db`. A server restart must preserve the database. The backup script must create a SQLite online snapshot, send it to restic, and allow restoration into a separate test directory.

## Idempotence and Recovery

Database initialization and Docker Compose startup are safe to repeat. Backup snapshots replace the local staging file atomically only after a SQLite integrity check; restic creates immutable encrypted snapshots. Before deployment, rotate the exposed bot token through BotFather. If a migration or rollout fails, stop the container and restore the latest verified restic snapshot into `/data/notes.db`.

## Artifacts and Notes

The implementation must not place real tokens, Telegram user IDs, machine-specific paths, or personal note content in tracked files.

## Interfaces and Dependencies

Keep `python-telegram-bot[job-queue]`, `python-dotenv`, and standard-library SQLite. Add no Python runtime dependency for deployment tooling. Require Docker Compose, `restic`, and Python 3 on the VPS host. Use S3-compatible restic environment variables from an untracked host file.

Revision note: created on 2026-05-30 to implement the production roadmap after reviewing the existing V1 assistant. Updated on 2026-05-30 after implementation and local validation to record completed work and the remaining owner-operated production actions. Updated again after hardening production preflight, callback privacy, settings-based JSON backup UX, import validation, day-plan synchronization, restore verification, overdue reminder handling, fail-closed owner access, anonymized interaction logs, environment validation, atomic import rollback, minimal-privilege VPS deployment, legacy SQLite migration compatibility, verified atomic snapshot replacement, container UID ownership checks, and host monitor state isolation.
