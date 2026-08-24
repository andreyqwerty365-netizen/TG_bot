from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .catalog import Exercise, ExerciseCatalog, ExerciseGroup
from .database import TrainerDatabase
from .exporter import build_workout_export
from .views import (
    after_save_keyboard,
    exercises_keyboard,
    format_number,
    groups_keyboard,
    history_keyboard,
    history_detail_keyboard,
    input_keyboard,
    sets_keyboard,
    trainer_main_menu,
    weight_editor_keyboard,
)

if TYPE_CHECKING:
    from ..application import BotApp
    from ..state import ChatState


logger = logging.getLogger(__name__)
REPS_BY_SET = (12, 10, 8)


def _parse_number(text: str | None, *, allow_zero: bool) -> float | None:
    try:
        value = round(float((text or "").strip().replace(",", ".")), 3)
    except ValueError:
        return None
    minimum = 0 if allow_zero else 0.000001
    return value if minimum <= value <= 1000 else None


def _initial_weights(base_weight: float, recent: tuple[float, ...], sets_count: int) -> list[float]:
    result = list(recent[:sets_count])
    fallback = result[-1] if result else base_weight
    result.extend([fallback] * (sets_count - len(result)))
    return result


def _set_weight_and_raise_following(weights: list[float], active_set: int, value: float) -> list[float]:
    weights[active_set] = value
    for index in range(active_set + 1, len(weights)):
        if weights[index] < value:
            weights[index] = value
    return weights


class TrainerHandlers:
    def __init__(self, database: TrainerDatabase, catalog: ExerciseCatalog, timezone: ZoneInfo) -> None:
        self.database = database
        self.catalog = catalog
        self.timezone = timezone

    async def command_trainer(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_main(app, context, update.effective_chat.id)

    async def command_workout(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_groups(app, context, update.effective_chat.id)

    async def command_history(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text, days = self._history_overview(update.effective_user.id)
        await app.send_active(
            context,
            update.effective_chat.id,
            text,
            reply_markup=history_keyboard(days),
        )

    async def command_export(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_export(app, context, update.effective_chat.id, update.effective_user.id)

    async def command_cancel(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        state = app.get_chat_state(context, update.effective_chat.id)
        if state.mode and state.mode.startswith("trainer_"):
            await self._cleanup_photo(context, update.effective_chat.id, state)
        await self._send_main(app, context, update.effective_chat.id)

    async def handle_callback(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        query = update.callback_query
        if query is None or update.effective_chat is None:
            return False
        data = query.data or ""
        if data != "menu:trainer" and not data.startswith("trainer:"):
            return False

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        state = app.get_chat_state(context, chat_id)

        if data.startswith("trainer:delta:"):
            try:
                requested_delta = float(data.rsplit(":", 1)[1])
                current_weights = [float(value) for value in state.payload.get("weights", [])]
                current_index = int(state.payload.get("active_set", 0))
                requested_weight = current_weights[current_index] + requested_delta
            except (ValueError, IndexError):
                requested_weight = 0
            if not 0 <= requested_weight <= 1000:
                await query.answer("Вес должен быть от 0 до 1000 кг", show_alert=True)
                return True

        await query.answer()

        if data in {"menu:trainer", "trainer:main", "trainer:cancel"}:
            await self._cleanup_photo(context, chat_id, state)
            state.mode = None
            state.payload = {}
            await query.edit_message_text("🏋️ Персональный тренер", reply_markup=trainer_main_menu())
            return True

        if data == "trainer:workout":
            await self._cleanup_photo(context, chat_id, state)
            state.mode = "trainer_group"
            state.payload = {}
            await query.edit_message_text("1. Выберите группу упражнений", reply_markup=groups_keyboard(self.catalog.groups))
            return True

        if data == "trainer:history":
            text, days = self._history_overview(user_id)
            await query.edit_message_text(text, reply_markup=history_keyboard(days))
            return True

        if data.startswith("trainer:history:"):
            selected_day = data.rsplit(":", 1)[1]
            try:
                date.fromisoformat(selected_day)
            except ValueError:
                text, days = self._history_overview(user_id)
                await query.edit_message_text(text, reply_markup=history_keyboard(days))
                return True
            await query.edit_message_text(
                self._history_day_text(user_id, selected_day),
                reply_markup=history_detail_keyboard(),
            )
            return True

        if data == "trainer:export":
            await self._send_export(app, context, chat_id, user_id)
            await query.edit_message_text("✅ Excel-файл отправлен.", reply_markup=trainer_main_menu())
            return True

        if data.startswith("trainer:group:") or data.startswith("trainer:again:"):
            group_id = data.rsplit(":", 1)[1]
            group = self.catalog.get_group(group_id)
            if group is None:
                await query.edit_message_text("Группа не найдена.", reply_markup=groups_keyboard(self.catalog.groups))
                return True
            state.mode = "trainer_exercise"
            state.payload = {"group_id": group.id}
            await query.edit_message_text(f"2. {group.name}: выберите упражнение", reply_markup=exercises_keyboard(group))
            return True

        if data.startswith("trainer:exercise:"):
            exercise_id = data.rsplit(":", 1)[1]
            resolved = self.catalog.get_exercise(exercise_id)
            if resolved is None:
                await query.edit_message_text("Упражнение не найдено.", reply_markup=groups_keyboard(self.catalog.groups))
                return True
            group, exercise = resolved
            state.payload = {"group_id": group.id, "exercise_id": exercise.id}
            await self._send_exercise_photo(context, chat_id, state, exercise)
            if exercise.type == "distance":
                state.mode = "trainer_distance"
                await query.edit_message_text(
                    f"{exercise.name}\n\nВведите дистанцию в километрах, например 2,4.",
                    reply_markup=input_keyboard("trainer:back:exercises"),
                )
            else:
                state.mode = "trainer_sets"
                await query.edit_message_text(
                    f"3. {exercise.name}: сколько подходов?\n\n1-й — 12 повторений\n2-й — 10\n3-й — 8",
                    reply_markup=sets_keyboard(),
                )
            return True

        if data == "trainer:back:exercises":
            await self._cleanup_photo(context, chat_id, state)
            group = self.catalog.get_group(str(state.payload.get("group_id", "")))
            if group is None:
                state.mode = "trainer_group"
                state.payload = {}
                await query.edit_message_text("1. Выберите группу упражнений", reply_markup=groups_keyboard(self.catalog.groups))
            else:
                state.mode = "trainer_exercise"
                state.payload = {"group_id": group.id}
                await query.edit_message_text(f"2. {group.name}: выберите упражнение", reply_markup=exercises_keyboard(group))
            return True

        if data == "trainer:back:sets":
            resolved = self._resolved_exercise(state)
            if resolved is None:
                await query.edit_message_text("Упражнение не найдено.", reply_markup=groups_keyboard(self.catalog.groups))
                return True
            _, exercise = resolved
            preserved = {key: state.payload[key] for key in ("group_id", "exercise_id", "photo_message_id") if key in state.payload}
            state.mode = "trainer_sets"
            state.payload = preserved
            await query.edit_message_text(
                f"3. {exercise.name}: сколько подходов?\n\n1-й — 12 повторений\n2-й — 10\n3-й — 8",
                reply_markup=sets_keyboard(),
            )
            return True

        if data.startswith("trainer:sets:"):
            try:
                sets_count = int(data.rsplit(":", 1)[1])
            except ValueError:
                return True
            if sets_count not in {1, 2, 3}:
                return True
            resolved = self._resolved_exercise(state)
            if resolved is None:
                await query.edit_message_text("Упражнение не найдено.", reply_markup=groups_keyboard(self.catalog.groups))
                return True
            _, exercise = resolved
            state.payload.update({"sets_count": sets_count, "active_set": 0})
            profile = self.database.get_profile(user_id, exercise.id)
            if profile is None:
                state.mode = "trainer_base_weight"
                await query.edit_message_text(
                    f"4. {exercise.name}: введите базовый вес в килограммах.",
                    reply_markup=input_keyboard(),
                )
            else:
                state.mode = "trainer_editing_weights"
                state.payload.update(
                    base_weight=profile.base_weight,
                    weights=_initial_weights(profile.base_weight, profile.last_weights, sets_count),
                )
                await self._render_editor(query, state, exercise)
            return True

        if data.startswith("trainer:active:"):
            index = int(data.rsplit(":", 1)[1])
            weights = state.payload.get("weights", [])
            if 0 <= index < len(weights):
                state.payload["active_set"] = index
                resolved = self._resolved_exercise(state)
                if resolved:
                    await self._render_editor(query, state, resolved[1])
            return True

        if data.startswith("trainer:delta:"):
            try:
                delta = float(data.rsplit(":", 1)[1])
            except ValueError:
                return True
            weights = [float(value) for value in state.payload.get("weights", [])]
            active_set = int(state.payload.get("active_set", 0))
            if not weights or not 0 <= active_set < len(weights):
                return True
            value = round(weights[active_set] + delta, 2)
            if not 0 <= value <= 1000:
                return True
            state.payload["weights"] = _set_weight_and_raise_following(weights, active_set, value)
            resolved = self._resolved_exercise(state)
            if resolved:
                await self._render_editor(query, state, resolved[1])
            return True

        if data == "trainer:manual":
            active_set = int(state.payload.get("active_set", 0))
            state.mode = "trainer_manual_weight"
            await query.edit_message_text(
                f"Введите вес для подхода №{active_set + 1}.",
                reply_markup=input_keyboard("trainer:editor:return"),
            )
            return True

        if data == "trainer:editor:return":
            resolved = self._resolved_exercise(state)
            if resolved:
                state.mode = "trainer_editing_weights"
                await self._render_editor(query, state, resolved[1])
            return True

        if data == "trainer:save":
            await self._save_strength(app, update, context, query, state)
            return True

        return True

    async def handle_text(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        chat_id = update.effective_chat.id
        state = app.get_chat_state(context, chat_id)
        if not state.mode or not state.mode.startswith("trainer_"):
            return False
        text = (update.message.text or "").strip()

        if state.mode == "trainer_base_weight":
            value = _parse_number(text, allow_zero=True)
            if value is None:
                await app.send_active(context, chat_id, "Введите вес числом от 0 до 1000.", reply_markup=input_keyboard())
                return True
            sets_count = int(state.payload["sets_count"])
            state.payload.update(base_weight=value, weights=[value] * sets_count, active_set=0)
            state.mode = "trainer_editing_weights"
            resolved = self._resolved_exercise(state)
            if resolved:
                await app.send_active(
                    context,
                    chat_id,
                    self._editor_text(resolved[1], state),
                    reply_markup=weight_editor_keyboard(resolved[1], state.payload["weights"], 0),
                )
            return True

        if state.mode == "trainer_manual_weight":
            value = _parse_number(text, allow_zero=True)
            if value is None:
                await app.send_active(context, chat_id, "Введите вес числом от 0 до 1000.", reply_markup=input_keyboard("trainer:editor:return"))
                return True
            weights = [float(item) for item in state.payload["weights"]]
            active_set = int(state.payload.get("active_set", 0))
            weights = _set_weight_and_raise_following(weights, active_set, value)
            state.payload["weights"] = weights
            state.mode = "trainer_editing_weights"
            resolved = self._resolved_exercise(state)
            if resolved:
                await app.send_active(
                    context,
                    chat_id,
                    self._editor_text(resolved[1], state),
                    reply_markup=weight_editor_keyboard(
                        resolved[1], weights, int(state.payload.get("active_set", 0))
                    ),
                )
            return True

        if state.mode == "trainer_distance":
            distance = _parse_number(text, allow_zero=False)
            if distance is None:
                await app.send_active(context, chat_id, "Введите дистанцию больше 0, например 2,4.", reply_markup=input_keyboard("trainer:back:exercises"))
                return True
            resolved = self._resolved_exercise(state)
            if resolved is None:
                await self._send_main(app, context, chat_id)
                return True
            group, exercise = resolved
            user = update.effective_user
            self.database.save_distance_activity(
                telegram_user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                group_id=group.id,
                group_name=group.name,
                exercise_id=exercise.id,
                exercise_name=exercise.name,
                distance_km=distance,
            )
            await self._cleanup_photo(context, chat_id, state)
            state.mode = None
            state.payload = {}
            await app.send_active(
                context,
                chat_id,
                f"✅ Кардио сохранено\n\n{exercise.name} — {format_number(distance)} км",
                reply_markup=after_save_keyboard(group.id),
            )
            return True

        return True

    async def _send_main(self, app: "BotApp", context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        state = app.get_chat_state(context, chat_id)
        state.mode = None
        state.payload = {}
        await app.send_active(context, chat_id, "🏋️ Персональный тренер", reply_markup=trainer_main_menu())

    async def _send_groups(self, app: "BotApp", context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        state = app.get_chat_state(context, chat_id)
        state.mode = "trainer_group"
        state.payload = {}
        await app.send_active(context, chat_id, "1. Выберите группу упражнений", reply_markup=groups_keyboard(self.catalog.groups))

    def _resolved_exercise(self, state: "ChatState") -> tuple[ExerciseGroup, Exercise] | None:
        exercise_id = str(state.payload.get("exercise_id", ""))
        resolved = self.catalog.get_exercise(exercise_id)
        if resolved is None or resolved[0].id != str(state.payload.get("group_id", "")):
            return None
        return resolved

    def _editor_text(self, exercise: Exercise, state: "ChatState") -> str:
        weights = [float(value) for value in state.payload["weights"]]
        scheme = "\n".join(
            f"{index + 1}. {REPS_BY_SET[index]} × {format_number(weight)} кг"
            for index, weight in enumerate(weights)
        )
        return f"{exercise.name}\n\nНастройте вес каждого подхода:\n{scheme}"

    async def _render_editor(self, query, state: "ChatState", exercise: Exercise) -> None:
        weights = [float(value) for value in state.payload["weights"]]
        await query.edit_message_text(
            self._editor_text(exercise, state),
            reply_markup=weight_editor_keyboard(exercise, weights, int(state.payload.get("active_set", 0))),
        )

    async def _save_strength(self, app: "BotApp", update: Update, context: ContextTypes.DEFAULT_TYPE, query, state: "ChatState") -> None:
        resolved = self._resolved_exercise(state)
        if resolved is None:
            await query.edit_message_text("Упражнение не найдено.", reply_markup=trainer_main_menu())
            return
        group, exercise = resolved
        weights = [float(value) for value in state.payload.get("weights", [])]
        if not weights:
            await query.edit_message_text("Сначала задайте рабочие веса.", reply_markup=sets_keyboard())
            return
        user = update.effective_user
        self.database.save_workout(
            telegram_user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            group_id=group.id,
            group_name=group.name,
            exercise_id=exercise.id,
            exercise_name=exercise.name,
            reps=REPS_BY_SET[: len(weights)],
            weights=weights,
            base_weight=float(state.payload["base_weight"]),
        )
        scheme = "; ".join(
            f"{rep}×{format_number(weight)} кг"
            for rep, weight in zip(REPS_BY_SET, weights, strict=False)
        )
        await self._cleanup_photo(context, update.effective_chat.id, state)
        state.mode = None
        state.payload = {}
        await query.edit_message_text(
            f"✅ Упражнение сохранено\n\n{group.name} → {exercise.name}\n{scheme}",
            reply_markup=after_save_keyboard(group.id),
        )

    def _history_overview(self, user_id: int) -> tuple[str, list[tuple[str, str]]]:
        workouts = self.database.get_recent_workouts(user_id, limit=50)
        if not workouts:
            return "История тренировок пока пуста.", []
        days: list[tuple[str, str]] = []
        seen: set[str] = set()
        for workout in workouts:
            completed = datetime.fromisoformat(workout.completed_at).astimezone(self.timezone)
            key = completed.date().isoformat()
            if key in seen:
                continue
            seen.add(key)
            days.append((key, f"🏋️ {completed:%d.%m.%Y}"))
            if len(days) == 5:
                break
        return "📋 Последние тренировки\n\nВыберите дату:", days

    def _history_day_text(self, user_id: int, selected_day: str) -> str:
        workouts = self.database.get_recent_workouts(user_id, limit=50)
        selected = date.fromisoformat(selected_day)
        lines = [f"🏋️ Тренировка {selected:%d.%m.%Y}"]
        found = False
        for workout in reversed(workouts):
            completed = datetime.fromisoformat(workout.completed_at).astimezone(self.timezone)
            if completed.date() != selected:
                continue
            found = True
            if workout.activity_type == "distance":
                details = f"{format_number(float(workout.distance_km or 0))} км"
            else:
                details = "; ".join(
                    f"{rep}×{format_number(weight)} кг"
                    for rep, weight in zip(workout.reps, workout.weights, strict=True)
                )
            resolved = self.catalog.get_exercise(workout.exercise_id)
            exercise_name = resolved[1].name if resolved is not None else workout.exercise_name
            lines.append(f"\n{completed:%H:%M} · {workout.group_name}\n{exercise_name}: {details}")
        if not found:
            return f"Тренировка за {selected:%d.%m.%Y} не найдена."
        return "\n".join(lines)

    async def _send_export(self, app: "BotApp", context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
        content = build_workout_export(self.database, user_id, self.timezone)
        document = BytesIO(content)
        document.name = "workout-history.xlsx"
        await context.bot.send_document(chat_id=chat_id, document=document, caption="Дневник тренировок")

    async def _send_exercise_photo(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, state: "ChatState", exercise: Exercise) -> None:
        path: Path | None = exercise.image_path
        if path is None or not path.is_file():
            return
        try:
            with path.open("rb") as image:
                message = await context.bot.send_photo(chat_id=chat_id, photo=image, caption=exercise.name)
            state.payload["photo_message_id"] = message.message_id
        except TelegramError:
            logger.warning("Failed to send trainer exercise image", exc_info=True)

    async def _cleanup_photo(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, state: "ChatState") -> None:
        message_id = state.payload.pop("photo_message_id", None)
        if not isinstance(message_id, int):
            return
        try:
            await context.bot.delete_message(chat_id, message_id)
        except TelegramError:
            pass
