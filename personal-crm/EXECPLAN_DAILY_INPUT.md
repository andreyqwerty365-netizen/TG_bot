# Keep daily input safe through overview and connection failures

This living ExecPlan follows `.agent/PLANS.md`. Changes stay in `personal-crm/` on `codex/personal-crm-reliability-web`; production data, integration permissions and the legacy receiver remain under their existing restrictions.

## Purpose / Big Picture

The owner can continue writing in Today while the overview refreshes or fails. A saved task remains available through its result link. A gateway or incomplete response gives a readable message that preserves uncertainty about a write, allowing the existing request identity to protect a retry from duplicates.

## Progress

- [x] (2026-10-15) Read repository instructions, requirements and current operational evidence; confirmed clean starting HEAD 04a96c7.
- [x] (2026-10-15) Reproduced five failing UI/API regressions before implementation.
- [x] (2026-10-15) Implement stable capture lifecycle and safe response errors.
- [x] (2026-10-15) React 19 passed, production build passed; 22 desktop/mobile browser checks passed in 30.6s against a new isolated PostgreSQL application.
- [x] (2026-10-15) Published implementation 24190535ec41419fea15a77a8dcd36adaf715c0c. Linux run 38733677815 both jobs success: 342 backend, 133 repository bot, 19 React, 22 browser, build/load and container HTTPS/restart/restore.
- [x] (2026-10-15) Built exact source on VPS, recorded prior images/private configuration and executable rollback, replaced only CRM api/source without migrations. Public ready200, new image confirmed, task/source/history counts and schema unchanged. Legacy/db/Caddy/backup container identities/start times/restarts unchanged.
- [x] (2026-10-15) Read-only live desktop/mobile checks passed: login, draft preservation on overview refresh/failure/retry, settings/logout, fresh source, verified CRM backup and all integrations disabled. No real task submitted.
- [x] (2026-10-15) Updated acceptance, user guide, operations and current handoff with observed evidence; documentation-only publication follows the tested implementation.

## Surprises & Discoveries

Today returned early whenever useLoad entered loading/error. This unmounted QuickCapture, including when its own successful save invoked changed. Regression tests lost both an unsent draft during refresh and the saved task link. The API parsed JSON before processing status 401; an empty unauthorized response did not expire the session, and HTML gateway diagnostics could appear in errors.

## Decision Log

2026-10-15: Keep capture mounted in the same location throughout overview loading/error; continue hiding stale task actions while loading. Add a local retry for the failed overview. Do not persist private drafts in browser storage or introduce automatic refresh that can overwrite edits.

2026-10-15: Handle session expiration before reading the body and translate unreadable responses to fixed Russian errors. A failed response does not establish whether the server committed the operation. Existing request IDs and version checks remain the retry mechanism.

## Context and Orientation

`web/src/screens.tsx` renders Today and `web/src/capture.tsx` owns its in-memory draft/result/request identities. `web/src/hooks.ts` marks each new GET loading, causing the old Today branches to remove the entire capture. `web/src/api.ts` is the shared fetch wrapper. Tests use synthetic records only. Production CRM has disabled real mail/AI/CRM Telegram; the separate legacy bot already runs and must not be restarted for this change.

## Plan of Work and Milestones

First implement the lifecycle/response fixes against the new `web/src/screens.test.tsx` and `web/src/api.test.ts` red tests. Then add browser regressions to the isolated existing browser suite to exercise real rendering on desktop/mobile, including delayed and failed overview responses and retry after an ambiguous write. Run all React tests and build. Use `scripts/cloud_checks.py` browser support or its documented command against a new disposable test database, never production. Publish only scoped changes without secrets. On Linux verify the source through CI before replacing CRM runtime; inspect actual old image IDs/config privately, save rollback, build exact source and restart only services whose application image changed. Check readiness and existing read-only pages; create no arbitrary real task.

## Concrete Steps

From `personal-crm/web`, run `npm.cmd test` and `npm.cmd run build`. The first targeted run failed all five added regressions: missing capture/result and JSON/status handling. Both final commands passed (19 unit cases). From `personal-crm`, run `.venv/Scripts/python.exe -X utf8 scripts/ci_databases.py --output .runtime/daily-input-databases.env` with loopback CRM_CI_ADMIN_URL and load its environment assignments. Set PLAYWRIGHT_BROWSERS_PATH to the existing `.runtime/browsers` and run `.venv/Scripts/python.exe -X utf8 scripts/browser_checks.py`: 22 passed in 30.6s. The runner creates only its own API/source processes and stops them afterward. Git publication must preserve the existing branch and draft PR #4; no merge or force push.

## Validation and Acceptance

Typing a draft and refreshing the overview preserves the text during loading, after a failed GET and after retry. A committed capture retains its result link after overview refresh. An HTML 502 never exposes diagnostic text; a truncated successful response states that the result is unknown; unreadable 401 expires the session. Desktop/mobile browsers validate the same user behavior. Production deployment requires preserved rollback and ready=200 without changing the legacy receiver or live integrations.

## Idempotence and Recovery

Tests only create synthetic records in new `personal_crm_test*` databases. Request identities are retained by the existing capture component until the owner changes input or receives a committed task. Production rollback uses recorded prior runtime image and existing private config; no schema changes are required. No production restore, destructive test setup or legacy bot restart is part of this plan.

## Outcomes & Retrospective

Local and Linux verification passed, implementation 2419053 is published and deployed to CRM api/source. The browser tests show a real PostgreSQL task committed before its response is replaced by HTML 502, then a retry produces only one matching task. They also verify retained drafts through failed overview/retry and a working saved-task result link. Live desktop/mobile read-only checks confirmed the deployed behavior with trusted HTTPS and real session authentication, without submitting a task. Independent alerting, scheduled restore drills, real mail/AI and CRM Telegram remain separate unfinished operational/product work; this iteration does not imply they are enabled. Drafts remain in memory only in the open Today section; navigation/reload still discards unsent text, as documented.

The private operator directory `/etc/personal-crm/operator/daily-input-2419053` contains previous deploy.env, sanitized before/after image evidence, build log, before/final record counts and rollback.sh. Runtime api/source now uses the image built from 2419053; CRM backup keeps its earlier verified 4232585 image. No automatic deployment was added. Production CLI Bearer verification was unavailable because this password-only configuration deliberately has no owner token; normal authenticated session GETs confirmed operational status instead.

## Artifacts and Notes

Initial targeted verification: `npm.cmd test -- src/screens.test.tsx src/api.test.ts`: 5 failed with the expected pre-fix symptoms.

Linux evidence: https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38733677815, source 24190535ec41419fea15a77a8dcd36adaf715c0c. Backend 342 passed in 60.09s (one existing Starlette warning), repository bot 133 passed in 3.59s, React19/build, desktop/mobile22 passed in 38.0s. Container rehearsal: actual Python3.12.15/PostgreSQL16.15/Caddy2.11.7, local-CA HTTPS, session restart, CSRF/origin and encrypted isolated restore passed. ASGI load 10000 tasks/10 clients p95 search/today/create 0.1547/0.2499/0.2478s; excludes public HTTP/TLS/VPS capacity. The archived live bot's separate 151-test runtime was not rebuilt or retested; the 133-test CI set is the repository bot, not that archive.
