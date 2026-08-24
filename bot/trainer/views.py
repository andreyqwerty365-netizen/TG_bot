from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .catalog import Exercise, ExerciseGroup


def format_number(value: float) -> str:
    return f"{value:g}"


def trainer_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏋️ Новая тренировка", callback_data="trainer:workout")],
            [
                InlineKeyboardButton("📋 История", callback_data="trainer:history"),
                InlineKeyboardButton("📊 Excel", callback_data="trainer:export"),
            ],
            [InlineKeyboardButton("⬅️ К секретарю", callback_data="menu:main")],
        ]
    )


def groups_keyboard(groups: tuple[ExerciseGroup, ...]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(group.name, callback_data=f"trainer:group:{group.id}")] for group in groups]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="trainer:main")])
    return InlineKeyboardMarkup(rows)


def exercises_keyboard(group: ExerciseGroup) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(exercise.name, callback_data=f"trainer:exercise:{exercise.id}")]
        for exercise in group.exercises
    ]
    rows.append([InlineKeyboardButton("⬅️ К группам", callback_data="trainer:workout")])
    return InlineKeyboardMarkup(rows)


def sets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1 подход", callback_data="trainer:sets:1"),
                InlineKeyboardButton("2 подхода", callback_data="trainer:sets:2"),
                InlineKeyboardButton("3 подхода", callback_data="trainer:sets:3"),
            ],
            [InlineKeyboardButton("⬅️ К упражнениям", callback_data="trainer:back:exercises")],
        ]
    )


def input_keyboard(back_callback: str = "trainer:back:sets") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
            [InlineKeyboardButton("❌ Отменить", callback_data="trainer:cancel")],
        ]
    )


def weight_editor_keyboard(exercise: Exercise, weights: list[float], active_set: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                ("✅ " if index == active_set else "") + f"{index + 1}: {format_number(weight)} кг",
                callback_data=f"trainer:active:{index}",
            )
            for index, weight in enumerate(weights)
        ]
    )
    for step in exercise.weight_steps:
        encoded = format_number(step)
        rows.append(
            [
                InlineKeyboardButton(f"−{encoded}", callback_data=f"trainer:delta:-{encoded}"),
                InlineKeyboardButton(f"+{encoded}", callback_data=f"trainer:delta:{encoded}"),
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton("⌨️ Ввести вес", callback_data="trainer:manual")],
            [InlineKeyboardButton("✅ Сохранить", callback_data="trainer:save")],
            [InlineKeyboardButton("⬅️ К подходам", callback_data="trainer:back:sets")],
            [InlineKeyboardButton("❌ Отменить", callback_data="trainer:cancel")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def after_save_keyboard(group_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Ещё упражнение", callback_data=f"trainer:again:{group_id}")],
            [InlineKeyboardButton("🏠 Меню тренера", callback_data="trainer:main")],
            [InlineKeyboardButton("⬅️ К секретарю", callback_data="menu:main")],
        ]
    )


def history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Выгрузить Excel", callback_data="trainer:export")],
            [InlineKeyboardButton("⬅️ Меню тренера", callback_data="trainer:main")],
        ]
    )
