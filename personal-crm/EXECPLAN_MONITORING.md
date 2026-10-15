# Detect failures and rehearse remote recovery regularly

This living ExecPlan follows `.agent/PLANS.md`. Scope is `personal-crm/` on the existing branch, with the existing Linux workflow permitted for validation. Do not merge or alter master. The user explicitly requested failure notifications, regular restore checks and GitHub publication on 15 October 2026, and subsequently chose a separate new technical Telegram bot and a free external monitor.

## Purpose / Big Picture

The owner receives technical alerts without involving the working reminder bot. Every week the server downloads the actual encrypted CRM and legacy backups from S3 and restores them in a disposable PostgreSQL instance and temporary SQLite files. A failure or missed run produces an alert; successful routine runs remain quiet. An external missing-heartbeat check detects loss of the whole VPS, which a same-server process cannot report.

## Progress

- [x] (2026-10-15) Confirmed running CRM/legacy healthy, current checkout aa88bbd, private S3 backup/timer available. Read backup/restore boundaries and existing procedures.
- [x] (2026-10-15) User chose a new technical Telegram bot, no existing external monitor; prepared free Healthchecks.io signup and empty owner-only local secret input. New bot and external account require user actions; do not substitute the old bot.
- [x] (2026-10-15) Observed9 red restore tests and6 red monitor tests before implementation;19 added cases now pass, including real PostgreSQL restore, both SQLite and stale/failed backup guards.
- [x] (2026-10-15) Implemented isolated restore job, weekly timer, status checks and deduplicated notification/heartbeat delivery. Windows full backend with disposable PG/UTF8:359 passed,2 platform skips,104.90s; one existing Starlette warning.
- [x] (2026-10-15) Published0199f81; Linux CI38737194516 both success:361 CRM/133 repository bot/19React/22browser/build/load/container HTTPS+restart+restore. On VPS UID10001/network-none/read-only-rootfs:17 new cases passed,2 DB cases deselected (already in full PostgreSQL CI).
- [x] (2026-10-15) Actual systemd restore downloaded real S3 and restored CRM PostgreSQL plus both SQLite; all components verified, Result=success/exit0, scratch stack removed. Original six service IDs/images/start times/restarts unchanged. Safe private reports retained.
- [x] (2026-10-15) Enabled monitor every2min and weekly restore Sunday04:20Moscow/Persistent. First restore manual run15:49MSK; next calendar18October04:20. Monitor timer actually triggered by calendar/monotonic scheduling afterward, service success/exit0. Local test alert/recovery delivered via the NEW bot; owner confirmed receipt. No production service stopped.
- [x] (2026-10-15) Healthchecks registration email did not arrive; owner chose Cronitor via social login. Created external HTTPS check, separate Ops Heartbeat and webhook/email Default list. Owner explicitly authorized new bot token+personal chatID in Cronitor. Observed real external HTTP200/Healthy and live VPS heartbeat. Published126b755 constrained Cronitor support; its CI38740174166 also success. Controlled external failure/recovery final evidence being recorded below.
- [x] (2026-10-15) Cronitor issue recorded FAIL13:11:58UTC and automatic TICK recovery13:13:19UTC; Alerts Sent confirms both alert and recovery delivered to email and the new-bot webhook. Billing shows Hacker Plan,2 monitors, no invoices. Final126b755 Linux CI:362 CRM/133 repository bot/19React/22browser; both jobs success, container HTTPS/restart/restore and load targets pass.
- [x] (2026-10-15) Final VPS13:17:50UTC: all8 probes true, external configured, both services success/exit0, timers active/enabled, next restore18October04:20MSK, ready200. All6 original container IDs/images/start/restarts and task/source/history/schema counts unchanged; no restore-db containers remain. Updated acceptance, operator/user docs and current handoff for publication in the same branch.

## Surprises & Discoveries

Existing backup download/restore APIs already authenticate and verify archives; CRM restore fences sessions/jobs/integrations. They can be reused without touching live data. Existing GitHub workflow only schedules on pushes to the feature branch; adding a cron there would not provide an independent monitor because scheduled Actions use the default branch, which is outside scope. Healthchecks.io free Hobbyist currently permits20 checks. BotFather creation and monitor account sign-in require the owner; these are configuration dependencies, not permission to use the existing bot.

The initial full Windows run overlapped a targeted regression against the same disposable test database, causing missing-table failures. No production DB was used. Repeated the entire suite serially on a newly generated separate database:359 passed/2 skipped. Future concurrent test commands must have different CRM_TEST_DATABASE_URL values. Healthchecks `/accounts/signup/` was unavailable; verified `/accounts/login/` and homepage provide the email-link signup/login flow instead.

The first UID10001 image test could not read an older root-private test source file in the checkout. Repeated with a separate temporary readable COPY of synthetic test/deploy code, not permissions changes to secrets or production, and all17 network-none cases passed. The first Telegram test raced owner Start and failed; subsequent getMe/confirmed owner Start and acknowledged test delivery passed. The empty Cronitor reminder field defaults to8hours; literal0 is rejected as Invalid interval, so external8h reminders are documented rather than falsely claimed disabled.

## Decision Log

2026-10-15: Use a disposable Compose project with its own internal PostgreSQL network and tmpfs data. The verifier has S3 credentials and encryption keys but no live PostgreSQL connection/network and no legacy source mount. Production DSN is used only to select the existing backup scope. Never run application workers or Telegram receivers against restored data.

2026-10-15: Host systemd checks monitor public HTTPS readiness, container health, source heartbeat, backup ages, restore status and disk capacity. State changes require repeated failures before alerting, and recovery follows only an acknowledged alert. Fixed texts exclude payloads and provider diagnostics. A separate external Healthchecks missing-heartbeat check covers total host/network failure; user-selected new bot carries notifications, with no receiver process required.

## Context and Orientation

`src/personal_crm/remote_backup.py` downloads the authenticated latest CRM archive and current erasure ledger. `recovery.restore_backup` requires an empty target with a restore-only name and fences all sends. `legacy_backup.download_restore` downloads/authenticates the latest two-SQLite archive and verifies schema/row fingerprints. The live server has root-private CRM and legacy configuration directories; no secrets or real records may enter Git. Existing `compose.production.yaml` and `compose.legacy-backup.yaml` stay operational. New jobs must be separate from the legacy receiver and not restart it.

## Plan of Work and Milestones

First create tests showing that the restore target must be the dedicated `restore-db` host and restore database, stale archives fail, both families are actually restored, and the report excludes payloads. Implement a derived ops image from the inspected backup base, a separate Compose stack, a bounded host wrapper and weekly Persistent timer. Check both sources independently so one failure does not hide the other. Remove only the exact per-run disposable project and temporary files in finally, including on timeout.

Then test and implement a small host monitor: it reads safe operational SQL/statuses, uses strict TLS, checks both backups/timer and weekly restore age, and persists an atomic transition state. Notifications only after two failures and on recovery; delivery failures do not mark an alert as sent. Optional external check URLs remain private and receive no task/mail/database content. Verify remote alerts with a controlled failure signal rather than breaking production. Final installation requires the new bot token and external account provided by the owner.

## Concrete Steps

From `personal-crm`, run `.venv/Scripts/python.exe -X utf8 -m pytest tests/test_restore_drill.py tests/test_ops_monitor.py -q` with disposable CRM_TEST_DATABASE_URL and CRM_TEST_PG_BIN. Observe red before implementing, then full backend tests and Linux CI. Build the ops image from a verified local CRM backup tag; record actual IDs privately. Install only new service/timer files and run an actual isolated restore. Do not update production CRM runtime or legacy receiver to ship an operator job.

## Validation and Acceptance

A real S3 download restores CRM into a separate temporary PostgreSQL16 and both SQLite into tmpfs; counts/fingerprints match authenticated manifests, sessions are revoked, reminders inactive and no application process is started. Stale/corrupt/missing backups fail visibly. Weekly timer is enabled with Persistent=true and bounded execution. The owner receives a controlled technical alert and recovery from the new bot. External monitor sees success/failure/missing ping independently; no secrets enter logs or Git. Original container IDs/start times/restarts and live data counts remain unchanged.

## Idempotence and Recovery

Use a host lock and unique project name; no cleanup by broad prefix enumeration. Restore targets cannot resolve to live data. Cleanup removes only exact verified per-run project and scratch path; preserve the safe last report. Existing config/timers remain unchanged. Disable only the new timers to roll back; keep images/source and original backups. User account/secret configuration can be retried without duplicate external checks.

## Outcomes & Retrospective

The local monitor and actual S3 recovery job are installed and verified independently of running CRM/legacy images. New-bot alerts/recovery and periodic monitor service succeed; weekly timer is enabled and the initial manual systemd restore passed. Cronitor HTTPS and heartbeat are healthy on the free Hacker Plan; its delivery log confirms both controlled alert and automatic recovery delivered to webhook/email. Next scheduled weekly run and reboot must not be claimed as observed after a manual service run. No payments/new paid services, original bot receiver, mail or AI configuration changes were made. The new ops image was derived from the inspected original CRM backup image and only used for recovery; application runtime remains2419053 and CRM backup4232585.
