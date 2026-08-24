# Telegram Assistant V1

This ExecPlan follows `.agent/PLANS.md`.

## Purpose

Turn the existing Telegram notes/reminders bot into a cleaner personal assistant for one owner. After the change, the owner can send one text phrase and the bot will either save a note or create a reminder, while unauthorized users are blocked. Voice messages are accepted only as a placeholder for a later speech-to-text stage.

## Progress

- [x] Reviewed current application, handlers, parser, views, settings, and tests.
- [x] Add owner allowlist through environment settings.
- [x] Simplify the main Telegram menu and reuse one capture flow for text.
- [x] Add a voice-message placeholder handler.
- [x] Expand reminder parsing for natural Russian phrases.
- [x] Add focused tests and run pytest with a local base temp path.

## Surprises & Discoveries

Pytest fails in the default Windows temp directory with `PermissionError` while creating pytest lock files. Validation should use an explicit local `--basetemp` path or a writable temp directory.

Even with a local `--basetemp`, this environment denied access to the generated pytest temp directory during cleanup. Parser and settings tests that do not need `tmp_path` passed, and modified Python files compile.

## Decision Log

Use the current bot instead of rewriting it. The repository already has SQLite persistence, job-queue reminders, import/export, search, day plans, and tests, so V1 should be an additive refinement.

Voice input is deferred. The handler will exist as a user-facing placeholder, and a later implementation can send the transcribed text into the same capture flow.

## Outcomes & Retrospective

Implemented the V1 refinement: owner allowlist, compact main menu, shared text capture flow, voice placeholder, and natural Russian reminder phrases. Full pytest remains blocked by the local temp-directory permission issue.
