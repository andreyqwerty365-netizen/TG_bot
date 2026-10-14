# Implement Russian input, isolated Telegram and gated Responses

This living plan follows `.agent/PLANS.md` and builds on the committed `personal-crm/EXECPLAN.md`. Work stays inside `personal-crm/` on `codex/personal-crm-telegram-gpt`, fetched at 1de2f965fb471dd76548df9294ea9661b1932072. No production receiver, database, bot or credentials are used.

## Purpose / Big Picture

An owner can submit a synthetic Telegram Update in Russian, get a committed task and exact reminder or a truthful clarification, complete or move the referenced task, and answer a version-bound question after restarting the process. A configurable Responses adapter interprets complex input only after all consent, model, price and budget gates pass. Its tests use the official SDK with mocked HTTP, not paid calls. Live Telegram/webhooks remain disabled until separately configured and authorized.

## Progress

- [x] (2026-10-14) Verified clean core branch; fetched the prepared Stage 2 branch. Only CODEX_TASK_STAGE2.md differs from core. Read root/project instructions, plans, task and implementation; existing PostgreSQL and local Compose are running.
- [x] (2026-10-14) Identified source-first/process lease, owner-row transaction boundary, proposal version checking and worker uncertainty semantics. Current reminders from interpreters always require confirmation; there is no persistent conversational context or reply queue.
- [x] (2026-10-14) M0: add metadata/dialogue/reply/budget schema and migration; record interface and policy decisions.
- [x] (2026-10-14) M1: implement bounded server context, limited deterministic Russian commands/dates and persistent version-bound clarification/confirmation.
- [x] (2026-10-14) M3 offline: authenticate synthetic/disabled real webhook Updates, deduplicate messages/revisions and queue truthful replies; implement disabled real test-bot transport.
- [x] (2026-10-14) M2: implement official Responses Structured Outputs, strict configuration gates and PostgreSQL budget reservation/settlement/cache; add 120+ labelled synthetic examples.
- [x] (2026-10-14) M4 validation: 124 CRM tests, 133 bot regression, official SDK mocks, core/Stage 2 demos, 28-day simulation and both local HTTP/Compose smokes passed. README, audit and acceptance matrix updated.
- [ ] M4 publication: complete final image/restart smoke, commit isolated changes and push stage2 commits; verify remote and clean working tree.

## Surprises & Discoveries

Stage 1 uses two-argument FixtureInterpreter and caches processed source results. It must remain compatible so existing tests and demos prove regression safety. Task changes/history/jobs already share owner locks and a single transaction. Proposal confirmation currently starts its own transaction; dialogue application must use the same internal transaction instead of nesting it. Sources store received_at/original_at but no channel metadata. Official openai 3.31.0 uses httpx2 rather than the core TestClient httpx dependency. Its Responses parsing implementation, official README/helpers and actual strict request body were inspected and verified with HTTP mocks. An outbound reply join needed explicit predicates, and forward edits must retain original channel authority. A replay must resume a pending source after a crash following receipt commit, while processed/error Updates remain idempotent.

## Decision Log

Only server deterministic parsing can authorize immediate owner commands; provider output cannot set its own authority. Untrusted forward/mail instructions may create a new obvious obligation or a proposal, never execute changes. Model outputs bind to source and allowed candidate IDs/versions. Date-only deadlines remain dates. Ambiguous boundaries, missing timezone, DST gaps/folds and old relative forwards ask questions rather than invent times.

Dialogue state is per owner/channel account, linked to a specific source/proposal/task version. It expires after 24 hours; an explicit reply identifies a question, and an unbound short reply addresses only the question belonging to the most recent source in that account. A new unrelated sentence does not consume dialogue. Reply jobs are stored atomically with result acknowledgement, unique per source version, and use the existing bounded delivery worker.

Monthly cost accounting uses integer micro-USD and PostgreSQL row locks. A trusted configured model input ceiling and max output tokens bound the reservation; prices, provenance and validity are explicit config with no default tariff. The SDK has zero retries. Uncertain paid outcomes retain the full conservative reservation as spent and cannot trigger an automatic second paid call for the source. No SDK client is constructed before gates pass.

## Outcomes & Retrospective

M0–M3 implemented. Baseline rerun was 69 passed in 10.75s; final full suite is 124 passed, one Starlette/AnyIO deprecation warning in 20.19s on real PostgreSQL. Official SDK mocked HTTP checks passed; 144 labelled synthetic cases include 36 held out. Stage 2 demo passed with seven fake replies, one exact delivery and persisted clarification after a new service/engine. Recovery/unrelated-error dialogue tests passed. Legacy regression: 133 passed in 1.07s. Core demo, 28-day simulation and both HTTP/Compose smokes passed; final image/restart smoke and publication are being completed. Real external NLP evaluation and real Telegram delivery are explicitly Not Run; they require separate user authorization, accounts and model/price choices.

## Context and Orientation

The core is under `personal-crm/src/personal_crm/`. `service.py` persists sources before interpretation and changes tasks/proposals/history/jobs. `schema.py` validates restricted operations. `models.py` defines PostgreSQL records, `api.py` authenticates the server-configured owner, and `worker.py` reserves a job for a short lease, records an attempt before sending and stops blind retries on uncertain delivery. A lease is a time-bounded reservation; an uncertain result means the provider may have accepted a request even without acknowledgement.

New `language.py` and `context.py` will produce bounded, owner-checked interpretation context and simple commands. `telegram.py` normalizes authenticated Updates and implements fake and explicitly enabled test-bot delivery. `openai_adapter.py` and `budget.py` implement the optional provider and spend ledger. Additive Alembic revisions add dialogue, channel metadata, reply jobs and budget tables; existing core migrations stay unchanged.

## Plan of Work

M0 introduces records for source metadata, conversational cursors/dialogue, durable replies and monthly budget reservations. M1 implements limited auditable Russian grammar and temporal validation, preserving unknown input honestly; refactors confirmation into a transaction helper and applies direct commands only from trusted server parsing. M3 adds the offline Update path first, then a disabled authenticated real webhook and disabled test-token transport, without polling or webhook installation. M2 inspects the installed official SDK, uses Responses strict schema/store=false, and reserves conservative funds before its request; fake HTTP checks verify payloads, errors, cache and concurrency. M4 supplies a reproducible Stage 2 CLI and labelled evaluation corpus, reruns regression suites/simulation/Compose, records unrun real-provider checks and publishes commits on this branch.

## Concrete Steps

From `/workspace/TG_bot/personal-crm`, use the existing `.venv` and local disposable PostgreSQL at port 55432. After changes:

    export CRM_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test
    .venv/bin/alembic upgrade head
    CRM_TEST_DATABASE_URL="$CRM_DATABASE_URL" .venv/bin/python -m pytest -q
    .venv/bin/python -m personal_crm.demo
    .venv/bin/python -m personal_crm.simulation

The new `.venv/bin/python -m personal_crm.stage2_demo` exercises Russian Updates, durable dialogue/reply jobs and fake exact delivery with zero external calls. Tests deliberately reset only an opt-in personal_crm_test* database. The existing Compose uses its own persisted synthetic database and ignored configuration; rebuild using the prepared wheel build context, then run its HTTP smoke. Never print secrets or copy existing bot settings.

## Validation and Acceptance

Run the fifteen scenarios from CODEX_TASK_STAGE2.md: exact owner reminder without confirmation, undated obligation, forward/waiting/old-date clarification, unambiguous completion and reminder-only move, overview without initiative cost, stale short confirmation, technical duplicate versus manual resend, authentication failure, injection boundaries, disabled/refused/invalid/timed-out AI and concurrent budget thresholds. Test DST gaps/folds, 23 числа and до пятницы, dialogue restart/expiry/unrelated input, edit revisions and uncertain reply delivery on PostgreSQL. Run the previous 69 CRM/133 bot checks again rather than quoting old counts. Mocked SDK performance is not model quality. Real model evaluation remains Not Run.

## Idempotence and Recovery

Use additive migrations and separate branch commits. Keep unknown provider reservations durable; no TTL can release potentially billed funds into another automatic call. Technical Update duplicates map to the same saved source/reply. Edited messages create a separate immutable source revision. Demo profiles are synthetic and unique per run; never truncate production or a user database. Only services started for this isolated module may be restarted. Raw keys, tokens, real messages and IDs never enter committed files or logs.

## Artifacts and Notes

Baseline remote core is d0e877eebd85af1271e06ba3fa6e9a2c70ec6d39. Prepared Stage 2 adds just its task. Prior reports of 69/133 tests are historical; actual new-run results will replace expectations after execution.

## Interfaces and Dependencies

Existing FixtureInterpreter.interpret(version_id, text) remains supported. ContextInterpreter.interpret_context(SourceContext) receives only authenticated, bounded context. Interpretation operations remain typed; only internal rule provenance permits direct execution. OutgoingReply and reply-kind Job provide post-commit acknowledgements. TelegramTransport follows success/error/unknown and timeout/authorization checks. ResponsesAdapter uses the official pinned OpenAI SDK, strict typed DTO and PostgreSQL budget ledger, and can be injected with mocked HTTP without reading actual secrets.

Revision 2026-10-14: established actual branch/schema boundaries and fake-only implementation plan before coding.

Revision 2026-10-14: completed M0–M3 implementation, recorded actual 118-test intermediate run and Stage 2 demo; final recovery/regression/Compose evidence remains in M4. Added independent corpus split and official SDK compatibility findings.

Revision 2026-10-14: recorded final 124/133 passing results, independent calendar validation, persistence recovery and both HTTP smokes. An unrelated failed parse advances the source cursor, preventing an accidental old unbound yes. Final publication remains pending.
