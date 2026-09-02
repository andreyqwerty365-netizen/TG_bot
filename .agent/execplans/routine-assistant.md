# Build a shift-aware daily routine assistant and a single-menu Telegram UI

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds. It is maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

After this change the bot has a smaller main menu, remembers which Telegram message is the current interactive menu even after a restart, and rejects buttons from older menu messages. The user can define whether a date is a day shift, night shift, or day off; explicitly start each day when actually awake; maintain reusable routine tasks relative to that click; mark tasks complete; and receive summaries containing only unfinished tasks that are still relevant.

## Progress

- [x] (2026-09-02 14:00+03:00) Inspected the current menu, callback, persistence, scheduling, and test architecture.
- [x] (2026-09-02 14:05+03:00) Recorded the product decisions and implementation plan.
- [x] (2026-09-02 14:20+03:00) Added red-green tests and implemented compact navigation plus persistent stale-menu protection.
- [x] (2026-09-02 14:35+03:00) Added red-green persistence/service tests and implemented shift schedules, routine tasks, completion, expiry, and delivery deduplication.
- [x] (2026-09-02 14:50+03:00) Added red-green UI/handler tests and implemented setup, task construction, wake settings, completion, and scheduled summaries.
- [x] (2026-09-02 15:00+03:00) Fixed simultaneous one-time/digest delivery with a reproducing test; full suite reports 124 passed and production preflight passes.
- [x] (2026-09-02 16:20+03:00) Replaced clock-based wake-up with an explicit “Начать день” action using red-green persistence, service, UI, and callback tests.
- [ ] Add monthly schedule import after receiving a representative screenshot of the user's real table layout.

## Surprises & Discoveries

- Observation: `BotApp.send_active` already tries to delete the prior menu, but the active message ID exists only in `application.bot_data`.
  Evidence: `bot/application.py` reads and writes `ACTIVE_KEY` without persisting it, so a process restart loses the pointer visible in the screenshots.
- Observation: callback handlers edit whichever Telegram message supplied the callback and do not verify that it is current.
  Evidence: `bot/handlers/callbacks.py` calls `query.edit_message_text` immediately after `query.answer` for navigation callbacks.
- Observation: the existing “План дня” is one fixed daily summary of ordinary reminders and cannot model shift-relative tasks or task expiry.
  Evidence: `chat_settings` contains only `dayplan_enabled` and `dayplan_time`, while `schedule_dayplan` registers one 24-hour repeating job.
- Observation: sending a due one-time prompt and a digest sequentially caused the second `send_active` call to delete the first prompt.
  Evidence: the regression test observed two sends at 10:00 when both categories were due; combining the task lists reduced this to one send.

## Decision Log

- Decision: Support exactly `day`, `night`, and `off` shift types.
  Rationale: The user explicitly corrected the earlier assumption about evening shifts.
  Date/Author: 2026-09-02 / Codex
- Decision: Keep “Сегодня” on the main menu and move “Последнее”, “Поиск”, and “Ближайшее” behind “Настройки” → “Дополнительные разделы”.
  Rationale: This matches the user’s explicit list while preserving quick access to the daily view, which becomes more useful with routines.
  Date/Author: 2026-09-02 / Codex
- Decision: Persist the active Telegram menu message ID in `chat_settings` and ignore callbacks originating from a different message ID.
  Rationale: Persistence fixes restart-related duplicates; validation prevents a historical keyboard from changing state even when Telegram cannot delete the old message.
  Date/Author: 2026-09-02 / Codex
- Decision: Store reusable routine tasks separately from ordinary reminders and store per-date completion separately from templates.
  Rationale: A routine task is reused across many shift days and needs per-routine-day status without generating an unbounded collection of ordinary reminders in advance.
  Date/Author: 2026-09-02 / Codex
- Decision: Define a routine day by the most recent configured shift wake-up within the last 24 hours, not by midnight.
  Rationale: Superseded by the manual-start decision below.
  Date/Author: 2026-09-02 / Codex
- Decision: Define the start of every routine day by the user's explicit “Начать день” click and keep the stored start across midnight.
  Rationale: Actual waking time varies on day, night, and off days; a Telegram bot cannot infer passive online presence reliably.
  Date/Author: 2026-09-02 / Codex
- Decision: Prefer screenshot-based monthly schedule import with a parsed preview and explicit confirmation, but defer the parser until a real schedule screenshot is available.
  Rationale: Shift-table layouts and labels vary; a sample is required to build and test reliable recognition without silently assigning incorrect shifts.
  Date/Author: 2026-09-02 / Codex
- Decision: Send one-time task prompts once, exclude them from later summaries, and include “until done” tasks in summaries until completion or expiry.
  Rationale: This directly models the user’s tooth-brushing and water example while permitting persistent tasks for the rest of the day.
  Date/Author: 2026-09-02 / Codex

## Outcomes & Retrospective

The compact menu, restart-safe single active message, three shift types, seven-day schedule editor, task constructor, manual day start, completion tracking, one-time prompts, and configurable two/three/four-hour summaries are implemented. The monthly screenshot parser remains intentionally deferred until the user supplies the real schedule format.

## Context and Orientation

The repository is a Python Telegram bot using `python-telegram-bot`, SQLite, and pytest. `bot/application.py` owns orchestration and scheduled jobs. `bot/db.py` owns schema and queries. `bot/views.py` builds Russian text and inline keyboards. `bot/handlers/callbacks.py` routes button presses, while `bot/handlers/messages.py` handles constructor text input. `bot/services/organizer.py` contains existing notes and reminder business logic. Tests live in `tests/`.

An “active menu” means the one bot-authored Telegram message whose inline buttons are allowed to mutate bot state. A “routine day” means the work/rest cycle that begins when the user presses “Начать день”. A “task template” is a reusable instruction, such as “выпить стакан воды”, attached to one or all shift types and scheduled as an offset in minutes after that click. A task marked one-time is delivered once and omitted from later digests. A task marked until-done is repeated in digest summaries until completed or until its expiry offset.

## Plan of Work

First, update view tests to express the compact main menu and additional-tools submenu. Add application and callback tests proving that the active message ID survives a new `BotApp` instance and that a callback from a mismatched message is answered but not executed. Then add the smallest schema and orchestration changes to pass those tests.

Second, add model and database tests for shift wake settings, per-date shift assignment, routine task creation/listing, per-date completion, and idempotent delivery records. Create `bot/services/routines.py` with pure selection logic for the active routine date, due one-time tasks, and digest contents. Test night-shift behavior across midnight and expiry before implementation.

Third, add view and callback tests for the routine main screen, seven-day schedule editor, wake-time settings, task constructor, and completion buttons. Wire a new “Рутина” button into the main menu. Extend callbacks and text handlers without replacing the existing notes, reminders, or trainer state flows.

Finally, add a single periodic JobQueue tick restored during `post_init`. The tick examines chats with routine mode enabled, sends each due one-time prompt at most once, and sends one digest per elapsed interval slot. Delivery records make repeated ticks and process restarts idempotent. Scheduled messages use the active-message mechanism so only one interactive context remains. Run focused tests throughout the red-green cycles, then the complete suite and project preflight.

## Concrete Steps

Run all commands from `D:\Проекты\БОТ_ТГ\telegram_assistant_combined`.

Create or change tests first and run focused files with:

    .venv\Scripts\python.exe -m pytest tests\test_views.py tests\test_application_runtime.py tests\test_callbacks.py -q

The first run for each behavior must fail because the new API or behavior is absent. Implement only enough production code to make it pass, then rerun the same command.

For routine persistence and selection logic run:

    .venv\Scripts\python.exe -m pytest tests\test_routines.py tests\test_db.py -q

For final verification run:

    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe tools\production_preflight.py

If startup can be exercised without taking over an already-running bot process, run `main.py` with the configured local environment and confirm initialization reaches polling without import or schema errors. Otherwise use the application-construction and `post_init` tests as the non-network startup proof and document that limitation.

## Validation and Acceptance

The main-menu test must show callbacks for record, trainer, notes, reminders, today, routine, and settings, with no direct last/search/next callbacks. The additional-tools submenu must expose last/search/next and a back button.

The stale-menu test must persist a current message ID, construct a callback update from a different ID, and observe that the query receives an “устарело” answer while no edit method or state-changing database operation is called. A new bot application over the same database must still read the active ID.

Routine tests must demonstrate all three shift types; no routine before a manual start; a night routine continuing after midnight; one-time tasks disappearing after their initial delivery; until-done tasks appearing in a three-hour digest; completed and expired tasks disappearing; and delivery keys preventing duplicate output after another tick or restart.

Handler tests must demonstrate configuring a date, changing wake-up time, creating a reusable task, opening today’s checklist, and marking a task complete. The full existing suite must finish with zero failures.

## Idempotence and Recovery

All schema creation uses `CREATE TABLE IF NOT EXISTS` and additive column migration, so initialization is safe to repeat. Shift assignments use an upsert keyed by chat and date. Completion and delivery records use unique keys so repeated callbacks or ticks are harmless. No existing notes, reminders, or trainer data is deleted. If a Telegram message cannot be deleted, the bot attempts to remove its keyboard and still records the new current message.

## Artifacts and Notes

The expected stale callback user-facing text is a short alert such as:

    Это меню устарело. Используй последнее сообщение бота.

The expected digest shape is:

    📋 Осталось на сегодня:
    1. Подготовить одежду на завтра

with completion buttons for the listed task IDs and a “Выполнить всё” action.

## Interfaces and Dependencies

No new third-party dependency is required. `bot/db.py` will expose persistence methods for active message IDs, routine settings, shift templates, shift schedules, routine tasks, task status, and delivery keys. `bot/services/routines.py` will expose deterministic functions that accept an explicit local `datetime` for testability and return a routine-day context plus selected tasks. `bot/views.py` will expose keyboards and text builders for additional tools and routine screens. `BotApp` will own `schedule_routine_tick`, `sync_routine_schedule`, and the asynchronous routine tick callback, using the existing JobQueue and timezone utilities.

Plan revision note (2026-09-02): Initial plan created after repository inspection and the user’s correction to exactly three shift types.

Plan revision note (2026-09-02): Marked implementation complete, recorded the simultaneous-delivery discovery, validation evidence, and the deferred bulk schedule format.

Plan revision note (2026-09-02): Replaced fixed wake times with manual day starts after the user clarified that wake time varies for every shift type; recorded the screenshot-import follow-up dependency.
