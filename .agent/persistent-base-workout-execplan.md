# Persist and guide the base workout

This ExecPlan is a living document maintained according to `.agent/PLANS.md`. It describes a change to the combined Telegram assistant so an unfinished base workout survives navigation to the secretary and bot restarts, while the existing checklist highlights the next exercise in the recommended order without preventing free selection.

## Purpose / Big Picture

After this change, a user may begin the seven-exercise base workout, complete some exercises, leave for the secretary, or encounter an Amvera restart. Opening the trainer again must show “Продолжить тренировку” with the saved checkmarks. The checklist must mark the earliest unfinished exercise in the configured base order as recommended, while every unfinished exercise remains clickable.

## Progress

- [x] (2026-08-24 18:22+03:00) Confirmed the root cause: base-session progress exists only in the shared in-memory `ChatState`; secretary navigation clears that state.
- [x] (2026-08-24 18:23+03:00) Added persistence and recommendation tests; confirmed three expected failures before implementation.
- [x] (2026-08-24 18:25+03:00) Added SQLite persistence for one active base session per Telegram user.
- [x] (2026-08-24 18:26+03:00) Made trainer entry, resume, old checklist callbacks, exercise saving, and finish use the persisted session.
- [x] (2026-08-24 18:26+03:00) Highlighted the next recommended unfinished exercise without adding buttons or restricting exercise choice.
- [x] (2026-08-24 18:28+03:00) Ran targeted tests, the full suite, and a safe startup construction check.

## Surprises & Discoveries

- Observation: Returning only to the trainer menu already preserves progress, but `menu:main` invokes `set_mode(..., None)`, replacing the shared payload with an empty dictionary.
  Evidence: a local reproduction printed `before_secretary trainer_base_paused {'base_session': True, 'base_completed': ['lat_pulldown']}` and then `after_secretary None {}`.

- Observation: Telegram may keep an old inline checklist visible after the server restarts. Clicking an exercise on that old message originally rebuilt an empty in-memory payload and could overwrite persisted checkmarks on the next save.
  Evidence: the added regression test first failed with `assert [] == ['lat_pulldown']`; hydrating persisted progress before every `trainer:base:*` callback made it pass.

## Decision Log

- Decision: Persist only the base session and completed exercise identifiers, not an unfinished weight-entry screen.
  Rationale: an exercise is recorded only after the user presses Save; preserving partially typed weights would add complexity and can restore stale input. The requested durable unit is workout progress.
  Date/Author: 2026-08-24 / Codex.

- Decision: Indicate the next exercise inside the existing checklist and explanatory text.
  Rationale: this keeps free ordering and adds no extra buttons. The recommendation is the first unfinished exercise in `BASE_WORKOUT_IDS`.
  Date/Author: 2026-08-24 / Codex.

## Outcomes & Retrospective

The active base session now lives in `workouts.sqlite3` and is restored after secretary navigation, `/start`, ordinary trainer re-entry, application reconstruction, and clicks on an old base checklist. Saving a strength or distance exercise updates the persisted checkmarks; explicit finish deletes only the active session. The base list displays `➡️` and a text hint for the first unfinished exercise in the recommended order while retaining every exercise callback. The final full suite passed with `107 passed in 3.04s`, and constructing the configured application printed `startup-build-ok`. Deliberately unchanged: partially entered but unsaved weights are transient and restart from the exercise selection screen.

## Context and Orientation

`bot/trainer/handlers.py` owns trainer callbacks and defines `BASE_WORKOUT_IDS`, the canonical recommended order. `bot/trainer/views.py` builds the trainer keyboards. `bot/trainer/database.py` owns the separate SQLite workout database. `bot/handlers/callbacks.py` owns secretary navigation and currently clears the shared `ChatState`. Tests for the integrated flow live in `tests/test_trainer_integration.py`, while database tests live in `tests/test_trainer_database.py`.

An active base session means that the user started the base-workout checklist but has not pressed “Завершить тренировку”. SQLite persistence means saving the list of completed exercise identifiers in `workouts.sqlite3`, which is mounted under Amvera’s persistent `/data` directory in production.

## Plan of Work

First, add tests proving that an active session can be written with one database object and read with a newly constructed object using the same file. Add an integration test that starts a workout, records progress, enters the secretary, constructs a fresh bot runtime, and confirms that the trainer offers resume with the same checkmark. Add view assertions that the first unfinished exercise carries the recommendation marker while all exercise callbacks remain present. Run these tests before production edits and confirm expected failures.

Then extend `TrainerDatabase` with an idempotently created `active_base_sessions` table keyed by Telegram user ID. Provide methods to retrieve, save, and delete the completed identifiers. Update trainer entry and resume to hydrate `ChatState` from this table, update the row after each saved base exercise, and delete it only when the user explicitly finishes the workout. Secretary navigation may continue clearing its own transient UI state because the trainer progress is now independent.

Finally, derive the next recommendation from the first identifier in `BASE_WORKOUT_IDS` not present in the persisted completion set. Pass it to the checklist view and include a short “Рекомендуется дальше” line. Do not add a new button and do not disable any exercise callback.

## Concrete Steps

Run all commands from `D:\Проекты\БОТ_ТГ\telegram_assistant_combined`. Use the project Python environment already established for this workspace.

After adding tests, run the targeted files and expect failures caused by missing active-session database methods or missing recommendation text:

    python -m pytest -q tests/test_trainer_database.py tests/test_trainer_integration.py

After implementation, rerun the same command and expect all targeted tests to pass. Then run:

    python -m pytest -q

Finally start `main.py` long enough to confirm initialization reaches the Telegram polling stage or fails only because a second live polling instance owns the token; no schema or import exception is acceptable.

## Validation and Acceptance

The change is accepted when a failing pre-change test demonstrates each requested behavior and all tests pass after implementation. In the user flow, complete “Верхний хват”, go to “Меню тренера”, then “К секретарю”, and reopen “Тренер”. The first button must be “Продолжить тренировку”; resuming must show the checkmark on “Верхний хват” and recommend “Бабочка”. Reconstructing `BotApp` against the same trainer database must produce the same result, which models an Amvera restart. All remaining exercises must still be selectable in any order. Pressing “Завершить тренировку” must remove the persisted active session.

## Idempotence and Recovery

The SQLite schema uses `CREATE TABLE IF NOT EXISTS`, so repeated startup is safe. Saving an active session is an upsert, so retries replace the same user row. Finishing deletes only the current user’s active-session row and does not delete workout history. If implementation fails partway, rerunning database initialization and tests is safe; existing completed workout rows remain untouched.

## Artifacts and Notes

Baseline verification before this change was `103 passed in 2.80s`. The targeted red run produced `3 failed, 26 passed`; the old-checklist edge test separately failed before its guard was added. Final verification produced `107 passed in 3.04s`, and the safe startup construction printed `startup-build-ok`.

## Interfaces and Dependencies

No new external dependency is required. `TrainerDatabase` will expose a small persistence interface returning completed exercise identifiers and accepting the Telegram user ID plus identifiers. `TrainerHandlers` will remain the orchestration layer and `trainer.views.base_workout_keyboard` will accept an optional recommended exercise identifier. Existing `python-telegram-bot` and standard-library SQLite remain unchanged.

Revision note: initial plan created to implement the two user-approved improvements and deliberately exclude timers, editable rep schemes, undo controls, and extra treadmill fields. Updated after implementation to record the stale-button edge case and final verification evidence.
