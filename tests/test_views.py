from datetime import UTC, datetime

from bot.models import Note, Reminder
from bot.views import data_menu, notes_menu, reminder_created_kb, reminders_menu, search_results_menu, settings_menu


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
