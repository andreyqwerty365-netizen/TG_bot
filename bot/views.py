from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .models import Note, Reminder
from .utils.date_utils import fmt_ru_date_or_time


MAIN = "main"
NOTES = "notes"
REMINDERS = "reminders"
SETTINGS = "settings"
INFO = "info"
PAGE_SIZE = 10


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Записать", callback_data="quick:new")],
            [InlineKeyboardButton("🏋️ Тренер", callback_data="menu:trainer")],
            [
                InlineKeyboardButton("📝 Заметки", callback_data="menu:notes"),
                InlineKeyboardButton("⏰ Напоминания", callback_data="menu:reminders"),
            ],
            [
                InlineKeyboardButton("📅 Сегодня", callback_data="quick:today"),
                InlineKeyboardButton("📌 Ближайшее", callback_data="quick:next"),
            ],
            [
                InlineKeyboardButton("🧾 Последнее", callback_data="quick:last"),
                InlineKeyboardButton("🔎 Поиск", callback_data="quick:search"),
            ],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
        ]
    )


def _number_rows(
    prefix: str,
    items: list[Note] | list[Reminder],
    *,
    start: int = 1,
    limit: int = PAGE_SIZE,
) -> list[list[InlineKeyboardButton]]:
    buttons = [
        InlineKeyboardButton(str(idx), callback_data=f"{prefix}:{item.id}")
        for idx, item in enumerate(items[:limit], start)
    ]
    return [buttons[i : i + 5] for i in range(0, len(buttons), 5)]


def _pagination_rows(prefix: str, page: int, total: int, page_size: int = PAGE_SIZE) -> list[list[InlineKeyboardButton]]:
    if total <= page_size:
        return []
    last_page = max(0, (total - 1) // page_size)
    buttons: list[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Новее", callback_data=f"{prefix}:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{last_page + 1}", callback_data=f"{prefix}:{page}"))
    if page < last_page:
        buttons.append(InlineKeyboardButton("Старее ➡️", callback_data=f"{prefix}:{page + 1}"))
    return [buttons]


def notes_menu(notes: list[Note] | None = None, *, page: int = 0, total: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton("➕ Новая заметка", callback_data="notes:new")]]
    if notes:
        rows.extend(_number_rows("notes:edit_card", notes, start=page * PAGE_SIZE + 1))
    rows.extend(_pagination_rows("notes:page", page, total))
    rows.extend(
        [
            [InlineKeyboardButton("🗃️ Архив заметок", callback_data="notes:archive_list")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def notes_archive_menu(notes: list[Note], *, page: int = 0, total: int = 0) -> InlineKeyboardMarkup:
    rows = _number_rows("notes:archive_card", notes, start=page * PAGE_SIZE + 1)
    rows.extend(_pagination_rows("notes:archive_page", page, total))
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:notes")])
    return InlineKeyboardMarkup(rows)


def note_edit_card_kb(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Текст", callback_data=f"notes:edit_text:{note_id}")],
            [InlineKeyboardButton("🗃️ В архив", callback_data=f"notes:archive:{note_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"notes:delete_confirm:{note_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:notes")],
        ]
    )


def note_archive_card_kb(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("↩️ Вернуть", callback_data=f"notes:restore:{note_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"notes:delete_confirm:{note_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="notes:archive_list")],
        ]
    )


def note_delete_confirm_kb(note_id: int, *, archived: bool = False) -> InlineKeyboardMarkup:
    back = f"notes:archive_card:{note_id}" if archived else f"notes:edit_card:{note_id}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ Да, удалить", callback_data=f"notes:delete:{note_id}")],
            [InlineKeyboardButton("⬅️ Отмена", callback_data=back)],
        ]
    )


def reminders_menu(reminders: list[Reminder] | None = None, *, page: int = 0, total: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton("➕ Новое напоминание", callback_data="reminders:new")]]
    if reminders:
        rows.extend(_number_rows("reminders:edit_card", reminders, start=page * PAGE_SIZE + 1))
    rows.extend(_pagination_rows("reminders:page", page, total))
    rows.extend(
        [
            [
                InlineKeyboardButton("📌 Ближайшее", callback_data="quick:next"),
                InlineKeyboardButton("⚠️ Просроченные", callback_data="quick:overdue"),
            ],
            [
                InlineKeyboardButton("📅 Сегодня", callback_data="quick:today"),
                InlineKeyboardButton("📆 Завтра", callback_data="quick:tomorrow"),
            ],
            [InlineKeyboardButton("🧹 Убрать выполненные", callback_data="reminders:cleanup_done")],
            [InlineKeyboardButton("🗃️ Архив напоминаний", callback_data="reminders:archive_list")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def reminders_archive_menu(reminders: list[Reminder], *, page: int = 0, total: int = 0) -> InlineKeyboardMarkup:
    rows = _number_rows("reminders:archive_card", reminders, start=page * PAGE_SIZE + 1)
    rows.extend(_pagination_rows("reminders:archive_page", page, total))
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:reminders")])
    return InlineKeyboardMarkup(rows)


def settings_menu(dayplan_enabled: bool) -> InlineKeyboardMarkup:
    title = "🌅 План дня: включён" if dayplan_enabled else "🌅 План дня: выключен"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🕒 Таймзона", callback_data="settings:tz")],
            [InlineKeyboardButton(title, callback_data="settings:dayplan_menu")],
            [InlineKeyboardButton("💾 Резервная копия", callback_data="settings:data_menu")],
            [InlineKeyboardButton("📊 Статистика", callback_data="settings:stats")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )


def data_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📤 Экспорт JSON", callback_data="settings:export")],
            [InlineKeyboardButton("📥 Импорт JSON", callback_data="settings:import")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:settings")],
        ]
    )


def dayplan_menu(dayplan_enabled: bool) -> InlineKeyboardMarkup:
    toggle = "Выключить" if dayplan_enabled else "Включить"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🌅 {toggle}", callback_data="settings:dayplan_toggle")],
            [InlineKeyboardButton("🕘 Время отправки", callback_data="settings:dayplan_time")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:settings")],
        ]
    )


def info_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🆔 Мой ID", callback_data="info:id")],
            [InlineKeyboardButton("📊 Статистика", callback_data="info:stats")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )


def cancel_kb(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=back_callback)]])


def reminder_entry_kb(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("5 минут", callback_data="reminders:preset:5"),
                InlineKeyboardButton("10 минут", callback_data="reminders:preset:10"),
                InlineKeyboardButton("30 минут", callback_data="reminders:preset:30"),
            ],
            [
                InlineKeyboardButton("1 час", callback_data="reminders:preset:60"),
                InlineKeyboardButton("3 часа", callback_data="reminders:preset:180"),
                InlineKeyboardButton("6 часов", callback_data="reminders:preset:360"),
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
        ]
    )


def quick_new_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏰ Примеры напоминаний", callback_data="quick:examples")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )


def quick_last_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Заметки", callback_data="menu:notes")],
            [InlineKeyboardButton("⏰ Напоминания", callback_data="menu:reminders")],
            [InlineKeyboardButton("📌 Ближайшее", callback_data="quick:next")],
            [InlineKeyboardButton("⚠️ Просроченные", callback_data="quick:overdue")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")],
        ]
    )


def reminder_fire_kb(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Готово", callback_data=f"reminders:done:{reminder_id}"),
                InlineKeyboardButton("10м", callback_data=f"reminders:snooze:{reminder_id}:10"),
                InlineKeyboardButton("1ч", callback_data=f"reminders:snooze:{reminder_id}:60"),
            ],
            [
                InlineKeyboardButton("📅 Завтра", callback_data=f"reminders:tomorrow:{reminder_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"reminders:edit_card:{reminder_id}"),
            ],
        ]
    )


def reminder_edit_card_kb(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Текст", callback_data=f"reminders:edit_text:{reminder_id}")],
            [InlineKeyboardButton("🕒 Время", callback_data=f"reminders:edit_time:{reminder_id}")],
            [InlineKeyboardButton("🔃 Повтор", callback_data=f"reminders:repeat_menu:{reminder_id}")],
            [
                InlineKeyboardButton("✅ Готово", callback_data=f"reminders:done:{reminder_id}"),
                InlineKeyboardButton("📅 Завтра", callback_data=f"reminders:tomorrow:{reminder_id}"),
            ],
            [InlineKeyboardButton("🗃️ В архив", callback_data=f"reminders:archive:{reminder_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"reminders:delete_confirm:{reminder_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu:reminders")],
        ]
    )


def reminder_repeat_menu(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Ежедневно", callback_data=f"reminders:repeat_set:{reminder_id}:day")],
            [InlineKeyboardButton("Еженедельно", callback_data=f"reminders:repeat_set:{reminder_id}:week")],
            [InlineKeyboardButton("Ежемесячно", callback_data=f"reminders:repeat_set:{reminder_id}:month")],
            [InlineKeyboardButton("Без повтора", callback_data=f"reminders:repeat_set:{reminder_id}:none")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"reminders:edit_card:{reminder_id}")],
        ]
    )


def reminder_created_kb(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Изменить", callback_data=f"reminders:edit_card:{reminder_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"reminders:archive:{reminder_id}")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="menu:main")],
        ]
    )


def reminder_archive_card_kb(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("↩️ Вернуть", callback_data=f"reminders:restore:{reminder_id}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"reminders:delete_confirm:{reminder_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="reminders:archive_list")],
        ]
    )


def reminder_delete_confirm_kb(reminder_id: int, *, archived: bool = False) -> InlineKeyboardMarkup:
    back = f"reminders:archive_card:{reminder_id}" if archived else f"reminders:edit_card:{reminder_id}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ Да, удалить", callback_data=f"reminders:delete:{reminder_id}")],
            [InlineKeyboardButton("⬅️ Отмена", callback_data=back)],
        ]
    )


def search_results_menu(notes: list[Note], reminders: list[Reminder]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if notes:
        buttons = [InlineKeyboardButton(f"📝 {idx}", callback_data=f"notes:edit_card:{note.id}") for idx, note in enumerate(notes, 1)]
        rows.extend(buttons[i : i + 5] for i in range(0, len(buttons), 5))
    if reminders:
        buttons = [
            InlineKeyboardButton(f"⏰ {idx}", callback_data=f"reminders:edit_card:{reminder.id}")
            for idx, reminder in enumerate(reminders, 1)
        ]
        rows.extend(buttons[i : i + 5] for i in range(0, len(buttons), 5))
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def build_notes_text(notes: list[Note], archived: bool = False, *, page: int = 0, total: int | None = None) -> str:
    title = "🗃️ Архив заметок" if archived else "📝 Последние заметки"
    if not notes:
        return f"{title}:\n(пока нет)"
    start = page * PAGE_SIZE + 1
    lines = [f"{idx}) {note.text}" for idx, note in enumerate(notes, start)]
    if total is not None and total > PAGE_SIZE:
        lines.append(f"\nСтраница {page + 1} из {(total - 1) // PAGE_SIZE + 1}")
    return title + ":\n" + "\n".join(lines)


def build_reminders_text(
    reminders: list[Reminder],
    tz_offset_minutes: int,
    archived: bool = False,
    *,
    page: int = 0,
    total: int | None = None,
) -> str:
    title = "🗃️ Архив напоминаний" if archived else "⏲️ Активные напоминания"
    if not reminders:
        return f"{title}:\n(пока нет)"
    lines: list[str] = []
    for idx, reminder in enumerate(reminders, page * PAGE_SIZE + 1):
        repeat_suffix = f" [повтор: {reminder.repeat_rule}]" if reminder.repeat_rule else ""
        done_suffix = " ✅" if reminder.done_at else ""
        lines.append(
            f"{idx}) {fmt_ru_date_or_time(reminder.remind_at, tz_offset_minutes)} — {reminder.text}{repeat_suffix}{done_suffix}"
        )
    if total is not None and total > PAGE_SIZE:
        lines.append(f"\nСтраница {page + 1} из {(total - 1) // PAGE_SIZE + 1}")
    return title + ":\n" + "\n".join(lines)


def build_last_text(notes: list[Note], reminders: list[Reminder], tz_offset_minutes: int) -> str:
    lines = ["📝 Последнее", ""]
    lines.append("Заметки:" if notes else "Заметки:\n(пока нет)")
    for idx, note in enumerate(notes, 1):
        lines.append(f"{idx}) {clip(note.text, 120)}")
    lines.append("")
    lines.append("Напоминания:" if reminders else "Напоминания:\n(пока нет)")
    for idx, reminder in enumerate(reminders, 1):
        lines.append(f"{idx}) {fmt_ru_date_or_time(reminder.remind_at, tz_offset_minutes)} — {clip(reminder.text, 120)}")
    return "\n".join(lines)
