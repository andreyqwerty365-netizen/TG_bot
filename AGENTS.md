# AGENTS

## Repository Scope

This repository is a Telegram reminder and notes bot written in Python. The entry point is `main.py`, which loads settings from `.env`, configures logging, builds the Telegram application in `bot/app.py`, and starts long polling.

When writing complex features or significant refactors, use an ExecPlan (as described in `.agent/PLANS.md`) from design to implementation.

## Project Stack

- Python 3.x
- `python-telegram-bot[job-queue]` for the Telegram bot and scheduled jobs
- `python-dotenv` for loading local environment variables
- SQLite via the standard library for persistence
- `pytest` for tests
- `pyinstaller` for Windows EXE packaging
- Windows helper scripts: `run.bat`, `build_exe.bat`, `backup_db.bat`, `run_silent.vbs`

## Repository Layout

- `main.py` starts the bot.
- `bot/config.py` reads `.env` into `Settings`.
- `bot/app.py` contains the main application flow, command handlers, callback handlers, reminder scheduling, and message processing.
- `bot/db.py` handles SQLite access.
- `bot/models.py` contains data models.
- `bot/ui.py` builds Telegram texts and inline keyboards.
- `bot/services/` contains reminder parsing, reminder actions, search, and import/export logic.
- `bot/utils/datetime_utils.py` contains timezone and formatting helpers.
- `tests/` contains the current automated test suite.

## Run And Build Commands

Run all commands from the repository root: `D:\botrr\telegram_bot_pro_v6_ready\telegram_bot_pro_v6_ready`.

Local Windows bootstrap:

    run.bat

Direct Python run after dependencies are installed:

    python main.py

Create or refresh the virtual environment manually:

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt

Run tests:

    .venv\Scripts\python.exe -m pytest

Build Windows EXE:

    build_exe.bat

Create a database backup:

    backup_db.bat

## Environment And Local Files

- `.env.example` is the template for local configuration.
- `.env` is the real local configuration file.
- `BOT_TOKEN` is required to start the bot.
- `BOT_DB_PATH` defaults to `notes.db`.
- `BOT_LOG_PATH` defaults to `logs/bot.log`.

Important repository rule: `run.bat` must create only an empty `BOT_TOKEN=` placeholder when `.env` is missing. Treat real tokens as sensitive data. Do not copy bot tokens into new files, tests, docs, commits, Docker images, or logs. Prefer `.env.example` placeholders and local secrets only.

## Code Rules

- Keep changes consistent with the current architecture. Put Telegram orchestration in `bot/app.py`, persistence in `bot/db.py`, UI text and keyboards in `bot/ui.py`, and reusable business logic in `bot/services/` or `bot/utils/`.
- Prefer small additive edits over large rewrites.
- Do not hardcode secrets, chat IDs, tokens, file paths outside the repo, or machine-specific values.
- Preserve existing environment variable names unless the change explicitly requires a migration.
- Keep SQLite-facing changes explicit and testable. If schema or query behavior changes, update or add tests in `tests/`.
- Prefer straightforward Python over premature abstractions. This codebase is currently simple and mostly module-oriented.
- Keep user-visible copy coherent with the existing Russian-language bot behavior unless the task explicitly changes wording.
- If you add a new command, callback branch, parser behavior, or database operation, add tests for the changed behavior when practical.
- Do not commit generated runtime files such as `notes.db`, `logs/`, `.venv/`, or `__pycache__/` contents.

## Communication Style

- Answer briefly and to the point by default. Expand only when the task requires detail, tradeoffs, or explicit validation notes.
- Keep Russian-language replies concise when the user writes in Russian.

## Chat Handoff Skill

- When the user asks to summarize the chat, pass context to a new chat, create a handoff, or uses similar wording, use the local skill at `.agent/skills/chat-handoff/SKILL.md`.
- The handoff must follow that skill: a copy-ready markdown block, no invented facts, no empty sections, and no extra commentary after the block.

## Self-Check Before Finishing

Before finishing a task in this repository:

1. Run the relevant tests. For most code changes, that means:

       .venv\Scripts\python.exe -m pytest

2. If you changed startup, settings, handlers, parsing, reminders, or persistence, verify the bot still starts:

       .venv\Scripts\python.exe main.py

3. If the bot is started locally, confirm these basics:
   - the app starts without import errors;
   - `.env` is read successfully;
   - the SQLite database file can be created or opened;
   - logs are written to the configured log path;
   - reminder-related flows still schedule jobs.

4. If you changed import/export, parsing, datetime, or database code, check the matching tests in `tests/` and add coverage for regressions.

5. If you changed packaging-related files, rerun:

       build_exe.bat

6. If you could not run a validation step, say that explicitly in the final handoff.

## Preferred Workflow For Agents

- Read the touched modules first, especially `main.py`, `bot/app.py`, and the matching service or test files.
- Make the smallest change that solves the task.
- Update tests alongside behavior changes.
- Validate locally before handing off.
- For larger work, write and maintain an ExecPlan in `.agent/PLANS.md` or in a task-specific ExecPlan document that follows that file.
