from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .database import TrainerDatabase


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _local_datetime(value: str, timezone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone).replace(tzinfo=None)


def _format_weight(value: float) -> str:
    return f"{value:g}"


def _style_sheet(sheet, table_name: str) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

    if sheet.max_row >= 2:
        table = Table(displayName=table_name, ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)

    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        width = min(max(max_length + 2, 12), 42)
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = width


def build_workout_export(database: TrainerDatabase, telegram_user_id: int, timezone: ZoneInfo) -> bytes:
    set_rows = database.get_export_sets(telegram_user_id)
    profile_rows = database.get_export_profiles(telegram_user_id)
    distance_rows = database.get_export_distances(telegram_user_id)

    workbook = Workbook()
    sets_sheet = workbook.active
    sets_sheet.title = "Подходы"
    sets_sheet.append(
        [
            "Дата и время",
            "Группа",
            "Упражнение",
            "№ тренировки",
            "№ подхода",
            "Повторения",
            "Вес, кг",
            "Базовый вес, кг",
            "Объём, кг",
        ]
    )
    for row in set_rows:
        completed_at = _local_datetime(row["completed_at"], timezone)
        sets_sheet.append(
            [
                completed_at,
                row["group_name"],
                row["exercise_name"],
                int(row["workout_id"]),
                int(row["set_number"]),
                int(row["reps"]),
                float(row["weight"]),
                float(row["base_weight"]) if row["base_weight"] is not None else None,
                round(float(row["weight"]) * int(row["reps"]), 2),
            ]
        )
    for cell in sets_sheet["A"][1:]:
        cell.number_format = "dd.mm.yyyy hh:mm"
    _style_sheet(sets_sheet, "WorkoutSets")

    workouts_sheet = workbook.create_sheet("Тренировки")
    workouts_sheet.append(
        [
            "Дата и время",
            "Группа",
            "Упражнение",
            "Количество подходов",
            "Схема",
            "Общий объём, кг",
        ]
    )
    grouped: OrderedDict[int, dict] = OrderedDict()
    for row in set_rows:
        workout_id = int(row["workout_id"])
        workout = grouped.setdefault(
            workout_id,
            {
                "completed_at": row["completed_at"],
                "group_name": row["group_name"],
                "exercise_name": row["exercise_name"],
                "sets": [],
            },
        )
        workout["sets"].append((int(row["reps"]), float(row["weight"])))

    for workout in grouped.values():
        scheme = "; ".join(
            f"{reps}×{_format_weight(weight)} кг" for reps, weight in workout["sets"]
        )
        volume = round(sum(reps * weight for reps, weight in workout["sets"]), 2)
        workouts_sheet.append(
            [
                _local_datetime(workout["completed_at"], timezone),
                workout["group_name"],
                workout["exercise_name"],
                len(workout["sets"]),
                scheme,
                volume,
            ]
        )
    for cell in workouts_sheet["A"][1:]:
        cell.number_format = "dd.mm.yyyy hh:mm"
    _style_sheet(workouts_sheet, "Workouts")

    cardio_sheet = workbook.create_sheet("Кардио")
    cardio_sheet.append(
        ["Дата и время", "Группа", "Упражнение", "№ занятия", "Дистанция, км"]
    )
    for row in distance_rows:
        cardio_sheet.append(
            [
                _local_datetime(row["completed_at"], timezone),
                row["group_name"],
                row["exercise_name"],
                int(row["workout_id"]),
                float(row["distance_km"]),
            ]
        )
    for cell in cardio_sheet["A"][1:]:
        cell.number_format = "dd.mm.yyyy hh:mm"
    _style_sheet(cardio_sheet, "CardioActivities")

    profiles_sheet = workbook.create_sheet("Базовые веса")
    profiles_sheet.append(
        [
            "Группа",
            "Упражнение",
            "Базовый вес, кг",
            "Последние рабочие веса, кг",
            "Первое занятие",
            "Последнее занятие",
        ]
    )
    for row in profile_rows:
        last_weights = [float(value) for value in json.loads(row["last_weights_json"])]
        profiles_sheet.append(
            [
                row["group_name"],
                row["exercise_name"],
                float(row["base_weight"]),
                "; ".join(_format_weight(value) for value in last_weights),
                _local_datetime(row["created_at"], timezone),
                _local_datetime(row["updated_at"], timezone),
            ]
        )
    for column in ("E", "F"):
        for cell in profiles_sheet[column][1:]:
            cell.number_format = "dd.mm.yyyy hh:mm"
    _style_sheet(profiles_sheet, "ExerciseProfiles")

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
