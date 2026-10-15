# Keep daily input safe through overview and connection failures

This living ExecPlan follows `.agent/PLANS.md`. Changes stay in `personal-crm/` on `codex/personal-crm-reliability-web`; production data, integration permissions and the legacy receiver remain under their existing restrictions.

## Purpose / Big Picture

The owner can continue writing in Today while the overview refreshes or fails. A saved task remains available through its result link. A gateway or incomplete response gives a readable message that preserves uncertainty about a write, allowing the existing request identity to protect a retry from duplicates.

## Progress

- [x] (2026-10-15) Read repository instructions, requirements and current operational evidence; confirmed clean starting HEAD 04a96c7.
- [x] (2026-10-15) Reproduced five failing UI/API regressions before implementation.
- [x] (2026-10-15) Implement stable capture lifecycle and safe response errors.
- [x] (2026-10-15) React 19 passed, production build passed; 22 desktop/mobile browser checks passed in 30.6s against a new isolated PostgreSQL application.
- [ ] Publish changes, verify Linux CI, deploy with recorded image rollback and verify read-only production health.
- [ ] Update acceptance, user guide and handoff with observed evidence.

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

Local implementation and verification passed. The browser tests show a real PostgreSQL task committed before its response is replaced by HTML 502, then a retry produces only one matching task. They also verify retained drafts through failed overview/retry and a working saved-task result link. Linux verification/publication/deployment are pending. Independent alerting, scheduled restore drills, real mail/AI and CRM Telegram remain separate unfinished operational/product work; this iteration does not imply they are enabled.

## Artifacts and Notes

Initial targeted verification: `npm.cmd test -- src/screens.test.tsx src/api.test.ts`: 5 failed with the expected pre-fix symptoms.
