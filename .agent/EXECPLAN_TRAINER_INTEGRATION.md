# Integrate the personal trainer into the Telegram assistant

This ExecPlan is a living document maintained in accordance with `.agent/PLANS.md`. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must remain current while the work proceeds.

## Purpose / Big Picture

After this change, one Telegram bot will have two clearly separated user-facing sections: the existing personal secretary and a new personal trainer. The secretary continues to manage notes and reminders. The trainer records strength workouts and treadmill distance, remembers baseline and recent working weights, shows workout history and exercise images, and exports an Excel workbook. A user opens the trainer from the main menu or with `/workout` and returns to the secretary without starting a second bot process.

## Progress

- [x] (2026-08-24 11:04Z) Audited the secretary and trainer prototypes and selected `python-telegram-bot` as the single Telegram framework.
- [x] (2026-08-24 11:04Z) Created the isolated working copy at `D:\Проекты\БОТ_ТГ\telegram_assistant_combined` without copying Git metadata, secrets, databases, logs, or virtual environments.
- [x] (2026-08-24 11:07Z) Added seven initially failing tests for the missing trainer modules, persistence, export, navigation and dependencies.
- [x] (2026-08-24 11:10Z) Implemented the framework-independent trainer catalog, persistence and Excel export; the focused suite passed 7 tests.
- [x] (2026-08-24 11:18Z) Implemented `python-telegram-bot` keyboards and handlers for strength, cardio, history, images and Excel export.
- [x] (2026-08-24 11:19Z) Integrated trainer commands, callback routing and trainer text states into the secretary application.
- [x] (2026-08-24 11:25Z) Added settings, assets, dependencies, Windows/Docker configuration and user documentation.
- [x] (2026-08-24 11:28Z) Copied the existing private `.env` and `notes.db` into the ignored working directory, configured the single owner allowlist from existing records, and preserved the originals.
- [x] (2026-08-24 11:29Z) Ran 87 tests, secret scanning, production preflight, a local construction smoke test and a bounded real Telegram polling startup.

## Surprises & Discoveries

- Observation: Both source bots use Python; only their Telegram frameworks differ.
  Evidence: the secretary imports `telegram.ext`, while the trainer prototype imports `aiogram`.

- Observation: The secretary is the safer integration base.
  Evidence: its existing suite has 74 passing tests and it already owns reminders, access control, deployment and backups; the trainer has four business-logic tests.

- Observation: The copied legacy `.env` did not contain `BOT_ALLOWED_USER_IDS`, while `chat_settings` was empty even though notes and reminders belonged to one chat.
  Evidence: distinct owner counts were zero in `chat_settings` and one in both `notes` and `reminders`. The combined copy now derives its private allowlist from that single shared owner without logging the identifier.

- Observation: A weight increment beyond 1000 kg initially answered one Telegram callback twice.
  Evidence: the regression test reported `Awaited 2 times`; validation was moved before the ordinary callback acknowledgement and the same test then passed.

## Decision Log

- Decision: Keep `python-telegram-bot` and port the trainer instead of running both frameworks or rewriting the secretary.
  Rationale: One bot token must have one update consumer, and the existing secretary already depends on `python-telegram-bot` JobQueue for reminder delivery. Porting the smaller trainer UI preserves tested behavior and removes the `aiogram` runtime dependency.
  Date/Author: 2026-08-24 / Codex.

- Decision: Use a separate SQLite file for workout data.
  Rationale: Keeping `notes.db` and `workouts.sqlite3` separate avoids a risky migration of the user's existing notes and makes either feature independently recoverable.
  Date/Author: 2026-08-24 / Codex.

- Decision: Prefix every trainer callback with `trainer:` and every trainer state with `trainer_`.
  Rationale: This prevents collisions with existing note and reminder callbacks and provides an explicit boundary between the two heads of the bot.
  Date/Author: 2026-08-24 / Codex.

## Outcomes & Retrospective

The combined bot now exposes the secretary and trainer through one `python-telegram-bot` Application. Strength workouts, cardio distance, baseline and recent weights, exercise images, history and Excel export are implemented with a separate workout database. The final suite reported `87 passed`; secret scanning and production preflight passed; local Application construction passed. A real polling run reached `Application started` and then stopped cleanly after the bounded launch check. The remaining validation is human interaction in Telegram to judge wording and button ergonomics, which can happen during the next iteration.

## Context and Orientation

The working repository root is `D:\Проекты\БОТ_ТГ\telegram_assistant_combined`. `main.py` loads `bot.config.Settings`, configures logging and starts long polling. `bot/application.py` constructs the `python-telegram-bot` Application, registers commands and owns shared state. `bot/handlers/callbacks.py` and `bot/handlers/messages.py` currently route all secretary button presses and text input. `bot/views.py` builds secretary keyboards.

The trainer prototype was unpacked at `D:\Проекты\БОТ_ТГ\gym_bot_source`. Its reusable concepts are `fitness_bot/catalog.py`, `fitness_bot/database.py`, `fitness_bot/exporter.py`, `exercises.json`, and `assets/exercises/`. Its `aiogram` handlers and keyboards are reference behavior only and must not be imported into the combined application.

The combined implementation will live under `bot/trainer/`. `bot/trainer/catalog.py` validates and reloads the JSON exercise catalog. `bot/trainer/database.py` owns the workout SQLite schema. `bot/trainer/exporter.py` creates the Excel export. `bot/trainer/views.py` creates `python-telegram-bot` inline keyboards and display texts. `bot/trainer/handlers.py` implements commands, callback routing and trainer-specific text states. The existing `ChatState` payload stores the in-progress workout.

## Plan of Work

First add tests for the desired trainer package, database behavior, Excel export, menu entry, callback prefixes and application command registration. Run the focused tests and observe failures caused by the missing feature.

Next implement the trainer catalog, database and exporter with no Telegram framework dependency. Copy the exercise JSON and images as data assets. Add `openpyxl` to `requirements.txt`. Run the focused tests until this business layer passes.

Then implement trainer views and handlers using only `python-telegram-bot`. The workflow is: trainer menu, group, exercise, strength set count or cardio distance, initial baseline weight when necessary, per-set weight editor, save, history and Excel export. Modify `bot/application.py` to construct the trainer services and register `/trainer`, `/workout`, `/workout_history`, `/workout_export`, and `/cancel`. Modify the existing callback and text entry points so trainer-prefixed input is delegated before secretary fallback behavior.

Finally update environment examples, run scripts, Docker packaging and README paths where required. Copy the user's `.env` and `notes.db` into the ignored working directory only after code verification so a local smoke test uses the real configuration without altering the originals. Startup validation must avoid long polling indefinitely: construct the Application and initialize both SQLite databases without contacting Telegram, then perform a bounded real startup only if network access and token state permit it.

## Concrete Steps

Run commands from `D:\Проекты\БОТ_ТГ\telegram_assistant_combined`.

Create and verify failing tests:

    .venv\Scripts\python.exe -m pytest tests\test_trainer_core.py tests\test_trainer_integration.py -q

After implementation, run the complete suite:

    .venv\Scripts\python.exe -m pytest -q

Run the no-secrets and production checks:

    .venv\Scripts\python.exe tools\check_no_secrets.py
    .venv\Scripts\python.exe tools\production_preflight.py

## Validation and Acceptance

The focused tests must be observed failing before production code exists and passing afterward. The complete suite must pass with no regression in the original 74 secretary tests.

Constructing `BotApp(Settings(...)).build()` with temporary notes and workout database paths must register the trainer commands and create both database schemas. The main keyboard must contain a trainer button. Every trainer callback must begin with `trainer:`.

In Telegram, `/start` must show the secretary menu with a `Тренер` entry. Selecting it must offer a new workout, history, export and return to the secretary. A strength workout must preserve the first baseline weight and update the most recent weights. Cardio must save a positive distance. The Excel export must contain the sheets `Подходы`, `Тренировки`, `Кардио`, and `Базовые веса`.

## Idempotence and Recovery

Schema creation uses `CREATE TABLE IF NOT EXISTS`, so repeated starts are safe. The original secretary directory and its `notes.db` remain untouched. If the integration fails, delete only the isolated combined directory and recreate it from the source; do not alter the original database. Runtime files remain excluded from source control.

## Artifacts and Notes

The original secretary is at `D:\SAVE\Проекты\ТГ боты\botrr\telegram_bot_pro_v6_ready\telegram_bot_pro_v6_ready`. The original monolithic predecessor is at `D:\SAVE\BOT\bot.py`. The trainer archive remains at `D:\Проекты\БОТ_ТГ\gym_bot.zip`.

## Interfaces and Dependencies

`bot.trainer.catalog.ExerciseCatalog(path: Path)` must expose groups, `get_group(group_id)` and `get_exercise(exercise_id)`. `bot.trainer.database.TrainerDatabase(path: Path)` must expose `init`, `get_profile`, `save_workout`, `save_distance_activity`, `get_recent_workouts`, and export query helpers. `bot.trainer.exporter.build_workout_export(database, telegram_user_id, timezone)` must return XLSX bytes.

`bot.trainer.handlers.TrainerHandlers` receives the catalog and database and exposes async command, callback and text methods. Its callback method returns whether it handled the update, and its text method returns whether the current state belonged to the trainer. No module in `bot/trainer/` may import `aiogram`.

Revision note (2026-08-24 11:04Z): Created the initial integration plan after selecting a single `python-telegram-bot` runtime and an isolated working copy.

Revision note (2026-08-24 11:29Z): Marked implementation and validation milestones complete, recorded the allowlist discovery, callback regression and final evidence.
