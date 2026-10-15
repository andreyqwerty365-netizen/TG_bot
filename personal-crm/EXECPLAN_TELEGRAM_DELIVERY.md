# Enable the owner's CRM reminders in Telegram

This living ExecPlan follows `.agent/PLANS.md`. Work only in personal-crm on codex/personal-crm-reliability-web. The user explicitly requested enabling CRM reminders, preserving the old bot and saving to GitHub on15October2026, then chose the already configured new @Technical_supp_bot. This authorizes outbound reminders to the existing confirmed personal chat, not a new ingress receiver or old-bot changes.

## Purpose / Big Picture

Reminders created in the web CRM reach the owner through the selected new bot. Existing technical alerts continue. No polling or webhook is needed for outbound delivery. A separately enabled monitor detects delivery worker absence/staleness. Verify a real scheduled synthetic reminder against an isolated test database rather than creating arbitrary production tasks.

## Progress

- [x] (2026-10-15) Checked production: ready200, queue empty, zero active reminders, recovery holdfalse, timezone Europe/Moscow. Saved original six container identities and private configuration rollback. Owner selected Technical_supp_bot.
- [x] (2026-10-15) Observed4 failing delivery-monitor cases, then15 monitor cases pass after implementing optional required-delivery container+heartbeat checks.
- [x] (2026-10-15) Existing CRM outbound network has noIPv6 and cannot reach Telegram overIPv4; old-bot network hasIPv6. Do not modify or attach to the old network.
- [x] (2026-10-15) Compose5.6 config validates separate IPv6-only egress; new-bot getMe/private getChat/empty webhook verified. Existing runtime scheduled an actual synthetic reminder8seconds ahead: idle/sent/idle, durable attemptsuccess, exactly1attempt; disposable PostgreSQL removed. Added failed/unknown queue guard after another observed red case.18 targeted monitor/network/transport checks pass; existing Starlette warning only.
- [x] (2026-10-15) Published9d145ad; enabled only delivery/API send-state using existing runtime image. Fresh13:32:46UTC monitor9/9healthy/externalconfigured, ready200, deliveryrunning/restarts0; API has no token/webhookfalse. All original images unchanged; source/db/backup/Caddy/legacy ID/start/restarts unchanged. Live tasks/sources/history/schema counts match. Private executable rollback saved.
- [x] (2026-10-15) Scheduled monitor13:34:48UTC again9/9healthy. Delivery heartbeat fresh/restarts0, all backup/restore/monitor timers active; no failed/unknown jobs. Existing digest hour9 retained; today's empty digest cancelled without sending. Synthetic test DB removed, original legacy/source/db/backup/Caddy identities unchanged. Linux CI38743431447 both jobs success, including full backend/bot/frontend/browser/load and HTTPS/restart/restore. Updated user/operator instructions, acceptance and current handoff for final publication.

## Surprises & Discoveries

The delivery worker/transport already implement durable attempts, exact reminders, cancellation, late-reminder guards and unknown-delivery protection. The production gate returns before consuming work when disabled. Monitor previously covered source but not delivery. First monitor test run produced expected4 failures; cache write permission warnings avoided with no:cacheprovider. The new CRM egress network supports verified IPv6 without reconfiguring existing production networks. Compose create does not accept no-deps; inspected its help and used up --no-start --no-deps, preserving all existing dependencies. The real synthetic send passed with existing runtime2419053; no application image/code change is needed.

## Decision Log

Use the existing confirmed new bot/chat as the owner explicitly selected. Keep webhook disabled and start no receiver. Token stays only in root-private delivery.env; API receives send-enabled state but no token. A new optional Compose override supplies an independent IPv6 network to delivery only. Preserve API/source runtime image2419053 and all existing images; operator monitor source can update independently. Do not migrate schema. Unknown send outcomes must never auto-retry.

## Context and Orientation

personal-crm/compose.production.yaml already has an optional telegram profile and delivery service. src/personal_crm/worker.py leases PostgreSQL jobs, records intent before TelegramTransport.send and records outcomes. telegram.py verifies getMe against explicit botID and restricts destination to configured allowlist. Private config is /etc/personal-crm/config; new bot token/chat are also in /etc/personal-crm/monitoring/monitor.json. Root-private baseline/rollback directory is /etc/personal-crm/operator/telegram-delivery-20261015. SSH owner permission lasts through16OctoberMoscow. No secrets/private IDs may enter Git or logs.

## Plan of Work

First validate a Compose override giving delivery an isolated IPv6 bridge while preserving existing data access. Add regression checks for changed network scope and monitor behavior. Publish on the existing branch and inspect Linux CI. On VPS use verified existing runtime image, create only the delivery network/container with no-deps and explicit overlay. Test transport identity and a synthetic due reminder in a separate temporary database with fixed text. Only after successful test enable production outbound configuration and API status; preserve old bot and other services. Readiness, real delivery heartbeat, monitor healthy and no unexpected task/source/history changes form acceptance.

## Validation and Acceptance

Run targeted pytest monitor/network/transport tests and Linux workflow. Real test send must be acknowledged with a provider messageID, durable attempt success and no second attempt on another worker tick. Delivery must report a fresh running heartbeat. An old-bot baseline comparison must prove same containerID/image/start/restart count. Public ready must return200 and external monitor remain healthy. Record what was not observed, including any future scheduled real user reminder/reboot.

## Idempotence and Recovery

Keep a copy of web.env/delivery.env/ingress.env/deploy.env before enabling. On failure stop only the new delivery service, restore these exact private configuration files and recreate only API if its flag changed. Do not run broad compose down or migrate, restart old bot, or remove existing volumes/networks. Delete only explicitly named synthetic test resources; do not alter live tasks to test delivery. Keep reports without task texts or secrets.

## Outcomes & Retrospective

Production outbound delivery is enabled through the owner-selected new bot, using the already tested runtime and an independent IPv6 network. Real scheduled synthetic delivery passed without changing live tasks. Technical alerts/restore timers remain enabled; the monitor now also covers delivery. Linux CI38743431447 both jobs passed, and actual scheduled monitor execution confirms healthy delivery. Future user-created reminders and reboot of this new worker are not yet observed. No old-bot changes or new receiving process were needed.
