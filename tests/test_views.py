from datetime import UTC, datetime

from bot.models import Note, Reminder
from bot.views import additional_tools_menu, data_menu, main_menu, notes_menu, reminder_created_kb, reminders_menu, routine_menu, routine_settings_menu, routine_task_policy_menu, search_results_menu, settings_menu


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_paginated_menus_include_navigation():
    note = Note(1, 1, "Текст", datetime(2026, 1, 1, tzinfo=UTC), False)
    reminder = Reminder(2, 1, "Созвон", datetime(2026, 1, 2, tzinfo=UTC), None, False, None, datetime(2026, 1, 1, tzinfo=UTC))

    assert "notes:page:1" in _callbacks(notes_menu([note], page=0, total=11))
    assert "reminders:page:1" in _callbacks(reminders_menu([reminder], page=0, total=11))


def test_search_and_created_reminder_keyboards_open_record_cards():
    note = Note(1, 1, "Текст", datetime(2026, 1, 1, tzinfo=UTC), False)
    reminder = Reminder(2, 1, "Созвон", datetime(2026, 1, 2, tzinfo=UTC), None, False, None, datetime(2026, 1, 1, tzinfo=UTC))

    callbacks = _callbacks(search_results_menu([note], [reminder]))
    assert "notes:edit_card:1" in callbacks
    assert "reminders:edit_card:2" in callbacks

    created_callbacks = _callbacks(reminder_created_kb(2))
    assert "reminders:edit_card:2" in created_callbacks
    assert "reminders:archive:2" in created_callbacks


def test_settings_menu_exposes_backup_actions():
    callbacks = _callbacks(settings_menu(False))
    assert "settings:data_menu" in callbacks
    assert "settings:stats" in callbacks

    data_callbacks = _callbacks(data_menu())
    assert "settings:export" in data_callbacks
    assert "settings:import" in data_callbacks


def test_main_menu_keeps_rare_tools_one_level_deeper():
    main_callbacks = _callbacks(main_menu())

    assert "menu:routine" in main_callbacks
    assert "quick:today" in main_callbacks
    assert "quick:last" not in main_callbacks
    assert "quick:search" not in main_callbacks
    assert "quick:next" not in main_callbacks

    settings_callbacks = _callbacks(settings_menu(False))
    assert "settings:additional_tools" in settings_callbacks

    tools_callbacks = _callbacks(additional_tools_menu())
    assert {"quick:last", "quick:search", "quick:next"} <= set(tools_callbacks)
    assert "menu:settings" in tools_callbacks


def test_routine_menu_exposes_schedule_tasks_and_settings():
    callbacks = _callbacks(routine_menu(False))
    assert {"routine:start", "routine:today", "routine:schedule", "routine:tasks", "routine:settings"} <= set(callbacks)
    assert "routine:toggle" in callbacks

    policy_callbacks = _callbacks(routine_task_policy_menu())
    assert {"routine:add_policy:once", "routine:add_policy:digest"} <= set(policy_callbacks)

    settings_callbacks = _callbacks(routine_settings_menu(False, 3, {"day": "07:00", "night": "19:00", "off": "09:00"}))
    assert not any(callback.startswith("routine:wake:") for callback in settings_callbacks)
