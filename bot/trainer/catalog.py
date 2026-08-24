from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ID_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")


@dataclass(frozen=True, slots=True)
class Exercise:
    id: str
    name: str
    weight_steps: tuple[float, ...]
    type: str = "strength"
    image_path: Path | None = None
    technique: tuple[str, ...] = ()
    mistakes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExerciseGroup:
    id: str
    name: str
    exercises: tuple[Exercise, ...]


class ExerciseCatalog:
    """Каталог с автоматической перезагрузкой при изменении JSON-файла."""

    def __init__(self, path: Path):
        self.path = path
        self._mtime_ns: int | None = None
        self._groups: tuple[ExerciseGroup, ...] = ()
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except FileNotFoundError as exc:
            raise RuntimeError(f"Не найден файл упражнений: {self.path}") from exc

        if not force and mtime_ns == self._mtime_ns:
            return

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Не удалось прочитать {self.path}: {exc}") from exc

        raw_groups = payload.get("groups")
        if not isinstance(raw_groups, list) or not raw_groups:
            raise ValueError("В exercises.json должен быть непустой массив groups")

        group_ids: set[str] = set()
        exercise_ids: set[str] = set()
        groups: list[ExerciseGroup] = []

        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                raise ValueError("Каждая группа должна быть объектом")
            group_id = self._validate_id(raw_group.get("id"), "ID группы")
            group_name = self._validate_name(raw_group.get("name"), "Название группы")
            if group_id in group_ids:
                raise ValueError(f"Повторяющийся ID группы: {group_id}")
            group_ids.add(group_id)

            raw_exercises = raw_group.get("exercises")
            if not isinstance(raw_exercises, list) or not raw_exercises:
                raise ValueError(f"В группе «{group_name}» нет упражнений")

            exercises: list[Exercise] = []
            for raw_exercise in raw_exercises:
                if not isinstance(raw_exercise, dict):
                    raise ValueError(f"Некорректное упражнение в группе «{group_name}»")
                exercise_id = self._validate_id(raw_exercise.get("id"), "ID упражнения")
                exercise_name = self._validate_name(
                    raw_exercise.get("name"), "Название упражнения"
                )
                if exercise_id in exercise_ids:
                    raise ValueError(f"Повторяющийся ID упражнения: {exercise_id}")
                exercise_ids.add(exercise_id)

                exercise_type = raw_exercise.get("type", "strength")
                if exercise_type not in {"strength", "distance"}:
                    raise ValueError(
                        f"Неизвестный type у упражнения «{exercise_name}»: {exercise_type}"
                    )
                steps = (
                    self._validate_steps(raw_exercise.get("weight_steps"))
                    if exercise_type == "strength"
                    else ()
                )
                image_path = self._validate_image_path(
                    raw_exercise.get("image"), exercise_name
                )
                technique = self._validate_notes(
                    raw_exercise.get("technique"), "technique", exercise_name
                )
                mistakes = self._validate_notes(
                    raw_exercise.get("mistakes"), "mistakes", exercise_name
                )
                exercises.append(
                    Exercise(
                        id=exercise_id,
                        name=exercise_name,
                        weight_steps=steps,
                        type=exercise_type,
                        image_path=image_path,
                        technique=technique,
                        mistakes=mistakes,
                    )
                )

            groups.append(ExerciseGroup(group_id, group_name, tuple(exercises)))

        self._groups = tuple(groups)
        self._mtime_ns = mtime_ns

    @staticmethod
    def _validate_id(value: object, label: str) -> str:
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            raise ValueError(f"{label} должен содержать только a-z, 0-9 и _ (до 40 символов)")
        return value

    @staticmethod
    def _validate_name(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} не задано")
        value = value.strip()
        if len(value) > 80:
            raise ValueError(f"{label} слишком длинное (максимум 80 символов)")
        return value

    @staticmethod
    def _validate_steps(value: object) -> tuple[float, ...]:
        if not isinstance(value, list) or not 1 <= len(value) <= 4:
            raise ValueError("weight_steps должен содержать от 1 до 4 значений")
        try:
            steps = sorted({round(float(item), 2) for item in value})
        except (TypeError, ValueError) as exc:
            raise ValueError("Все weight_steps должны быть числами") from exc
        if any(step <= 0 or step > 100 for step in steps):
            raise ValueError("Шаг веса должен быть больше 0 и не больше 100 кг")
        return tuple(steps)

    def _validate_image_path(self, value: object, exercise_name: str) -> Path | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Некорректное поле image у упражнения «{exercise_name}»")

        relative_path = Path(value.strip())
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(
                f"image у упражнения «{exercise_name}» должен быть относительным путём"
            )
        if relative_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError(
                f"Картинка упражнения «{exercise_name}» должна быть JPG или PNG"
            )

        project_dir = self.path.parent.resolve()
        image_path = (project_dir / relative_path).resolve()
        if not image_path.is_relative_to(project_dir) or not image_path.is_file():
            raise ValueError(
                f"Не найдена картинка упражнения «{exercise_name}»: {relative_path}"
            )
        return image_path

    @staticmethod
    def _validate_notes(
        value: object, field_name: str, exercise_name: str
    ) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or len(value) > 8:
            raise ValueError(
                f"{field_name} у упражнения «{exercise_name}» должен быть массивом до 8 строк"
            )
        notes: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 160:
                raise ValueError(
                    f"Некорректная строка в {field_name} у упражнения «{exercise_name}»"
                )
            notes.append(item.strip())
        return tuple(notes)

    @property
    def groups(self) -> tuple[ExerciseGroup, ...]:
        self.reload()
        return self._groups

    def get_group(self, group_id: str) -> ExerciseGroup | None:
        return next((group for group in self.groups if group.id == group_id), None)

    def get_exercise(self, exercise_id: str) -> tuple[ExerciseGroup, Exercise] | None:
        for group in self.groups:
            for exercise in group.exercises:
                if exercise.id == exercise_id:
                    return group, exercise
        return None
