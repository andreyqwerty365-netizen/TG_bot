"""A limited, documented grammar; unknown Russian needs a gated provider or clarification."""
from datetime import UTC, date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .schema import Deadline, Interpretation

WEEKDAYS = {"понедельник": 0, "вторник": 1, "среду": 2, "четверг": 3, "пятницу": 4, "субботу": 5, "воскресенье": 6}


class AmbiguousDate(ValueError):
    pass


def local_instant(day, wall_time, timezone):
    naive = datetime.combine(day, wall_time)
    zone = ZoneInfo(timezone)
    instants = {naive.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1)
                if naive.replace(tzinfo=zone, fold=fold).astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive}
    if len(instants) != 1:
        raise AmbiguousDate("Это время неоднозначно или отсутствует из-за перевода часов. Укажите точный момент с UTC-смещением.")
    return instants.pop()


def resolve_date_time(phrase, context, existing_time=None, require_time=True):
    if not context.timezone:
        raise AmbiguousDate("Сначала явно задайте часовой пояс профиля.")
    if context.channel != "owner" and re.search(r"завтра|сегодня|послезавтра|в (?:" + "|".join(WEEKDAYS) + ")", phrase):
        raise AmbiguousDate("В пересылке относительная дата может относиться к другому дню или поясу. Уточните дату и время.")
    if re.search(r"\bдо\b|\b\d{1,2} числа\b", phrase):
        raise AmbiguousDate("Уточните полный срок и границу даты; время и месяц не буду угадывать.")
    phrase = phrase.strip().lower()
    base = context.received_at.astimezone(ZoneInfo(context.timezone))
    clock = re.search(r"(?:\bв\s+)?(\d{1,2}):(\d{2})\b", phrase)
    if clock:
        hour, minute = map(int, clock.groups())
        if hour > 23 or minute > 59:
            raise AmbiguousDate("Некорректное время. Укажите часы и минуты.")
        wall = datetime.min.replace(hour=hour, minute=minute).time()
        phrase = (phrase[:clock.start()] + phrase[clock.end():]).strip()
    else:
        wall = existing_time
    phrase = re.sub(r"^(?:на|в)\s+", "", phrase).strip()
    offsets = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
    if phrase in offsets:
        day = base.date() + timedelta(days=offsets[phrase])
    elif phrase in WEEKDAYS:
        delta = (WEEKDAYS[phrase] - base.weekday()) % 7
        if delta == 0:
            raise AmbiguousDate("Вы имеете в виду сегодня или следующий такой день?")
        day = base.date() + timedelta(days=delta)
    else:
        try:
            day = date.fromisoformat(phrase)
        except ValueError:
            raise AmbiguousDate("Укажите полную дату и, для напоминания, точное время.")
    if require_time:
        if wall is None:
            raise AmbiguousDate("На какое точное время поставить напоминание?")
        return local_instant(day, wall, context.timezone)
    return day


def question(context, text, pending=None, dialogue=None):
    return Interpretation(source_version_id=context.source_version_id, operation="clarify", question=text,
                          pending_action=pending, dialogue_id=dialogue)


def selected_question(context):
    if context.reply_source_id:
        matches = [q for q in context.questions if q.source_version_id == context.reply_source_id]
    else:
        matches = [q for q in context.questions if q.source_version_id == context.last_source_id]
    return matches[0] if len(matches) == 1 else None


def select_task(context, subject=None, last=False, reminders_only=False):
    if context.reply_source_id and context.candidates:
        # Context builder places an owned task linked to this source first; verify its provenance separately.
        # A reply without a matching task does not grant a default selection.
        linked = getattr(context, "reply_task_id", None)
        matches = [t for t in context.candidates if t.id == linked]
    elif last:
        identity = context.last_reminder_task_id if reminders_only else context.last_task_id
        matches = [t for t in context.candidates if t.id == identity and (not reminders_only or t.reminder_at)]
        if not matches and reminders_only and context.candidates_complete:
            matches = [t for t in context.candidates if t.reminder_at]
    elif not context.candidates_complete:
        # Bounded model context cannot prove uniqueness across omitted tasks.
        return None
    elif subject:
        words = {w for w in re.findall(r"[а-яёa-z]{3,}", subject.lower()) if w not in {"задачу", "задача", "дело"}}
        matches = [t for t in context.candidates if words and all(w in t.title.lower() for w in words)]
    else:
        matches = [t for t in context.candidates if t.reminder_at] if reminders_only else context.candidates
    return matches[0] if len(matches) == 1 else None


def deterministic(context):
    text = context.text.strip()
    lowered = text.lower().strip(" .!?")
    if context.unsupported_media:
        return question(context, "Источник сохранён. Голос, медиа и вложения не анализировались.")
    if context.channel == "owner" and lowered in {"да", "нет"}:
        bound = selected_question(context)
        if bound and bound.proposal_id:
            return Interpretation(source_version_id=context.source_version_id, operation="answer", dialogue_id=bound.id,
                                  accepted=lowered == "да")
        return question(context, "Уточните, на какое предложение отвечаете; можно ответить на конкретное сообщение.")
    bound = selected_question(context) if context.channel == "owner" else None
    if bound and bound.pending_action and re.fullmatch(r"(?:на |в )?(?:сегодня|завтра|послезавтра|" + "|".join(WEEKDAYS) + r"|\d{4}-\d{2}-\d{2})(?: в \d{1,2}:\d{2})?", lowered):
        action = bound.pending_action
        target = next((t for t in context.candidates if t.id == action.get("target_id")), None)
        wall = target.reminder_at.astimezone(ZoneInfo(context.timezone)).time().replace(tzinfo=None) if target and target.reminder_at and context.timezone else None
        try:
            at = resolve_date_time(lowered, context, wall, action.get("change") not in ("plan", "deadline") or
                                   (action.get("change") == "deadline" and bool(re.search(r"\d{1,2}:\d{2}", lowered))))
        except AmbiguousDate as error:
            return question(context, str(error), action, bound.id)
        if action.get("change") == "deadline":
            temporal = {"deadline": Deadline(precision="instant" if isinstance(at, datetime) else "date",
                        value=at.isoformat(), original=text, timezone=context.timezone)}
        else:
            temporal = {"planned_on": at} if action.get("change") == "plan" else {"reminder_at": at}
        return Interpretation(source_version_id=context.source_version_id, **{**action, **temporal,
                               "dialogue_id": bound.id, "pending_action": None})
    if context.channel == "owner" and lowered in {"что на сегодня", "что сегодня", "покажи план", "план на сегодня"}:
        return Interpretation(source_version_id=context.source_version_id, operation="overview")
    if context.channel == "owner":
        close = re.fullmatch(r"(?:последнее|последнюю задачу) (?:выполнил|сделал|закончил)", lowered)
        generic_close = lowered in {"выполнил задачу", "задачу выполнил", "выполнил", "сделал"}
        subject_close = re.fullmatch(r"(.+?) (?:обновил|выполнил|сделал|закончил)", lowered)
        if close or generic_close or subject_close:
            task = select_task(context, subject_close.group(1) if subject_close and not close else None, bool(close))
            if not task:
                return question(context, "Какое именно дело выполнено? Ответьте на сообщение о нём или назовите его.")
            return Interpretation(source_version_id=context.source_version_id, operation="command", target_id=task.id,
                                  target_version=task.version, change="close")
        move = re.fullmatch(r"перенеси (последнее )?(напоминание|план|дедлайн) (?:на )?(.+)", lowered)
        if move:
            task = select_task(context, last=bool(move.group(1)), reminders_only=move.group(2) == "напоминание")
            if not task:
                return question(context, "Какое дело переносим? Ответьте на его сообщение или уточните название.")
            change = {"напоминание": "reminder", "план": "plan", "дедлайн": "deadline"}[move.group(2)]
            pending = {"operation": "command", "target_id": task.id, "target_version": task.version, "change": change}
            wall = task.reminder_at.astimezone(ZoneInfo(context.timezone)).time().replace(tzinfo=None) if task.reminder_at and context.timezone else None
            try:
                value = resolve_date_time(move.group(3), context, wall, change == "reminder" or
                                          (change == "deadline" and bool(re.search(r"\d{1,2}:\d{2}", move.group(3)))))
            except AmbiguousDate as error:
                return question(context, str(error), pending)
            if change == "deadline":
                temporal = {"deadline": Deadline(precision="instant" if isinstance(value, datetime) else "date",
                            value=value.isoformat(), original=text, timezone=context.timezone)}
            else:
                temporal = {"reminder_at": value} if change == "reminder" else {"planned_on": value}
            return Interpretation(source_version_id=context.source_version_id, **pending, **temporal)
    remind = re.fullmatch(r"(.+?)\s+напомни(?: мне)?\s+(.+)", lowered)
    if context.channel == "owner" and remind:
        title = text[remind.start(2):].strip(" .!?")
        pending = {"operation": "create", "title": title, "kind": "task", "obvious": True}
        try:
            at = resolve_date_time(remind.group(1), context)
        except AmbiguousDate as error:
            return question(context, str(error), pending)
        return Interpretation(source_version_id=context.source_version_id, **pending, reminder_at=at)
    if context.channel == "owner" and lowered.startswith("надо "):
        title = text[5:].strip(" .!?")
        if re.search(r"\bдо\b|\d{1,2} числа", title.lower()):
            return question(context, "Уточните полный срок и границу даты; дедлайн не назначен.")
        if re.match(r"(?:добавить|обновить|подготовить|купить|проверить|сделать|написать|позвонить)\b", title.lower()):
            return Interpretation(source_version_id=context.source_version_id, operation="create", title=title, obvious=True)
    if context.channel == "forward":
        if re.search(r"завтра|сегодня|послезавтра|\bдо\b|\d{1,2} числа", lowered):
            return question(context, "Уточните дату, время и исполнителя в пересылке; её относительные даты не пересчитаны от сегодняшнего дня.")
        promise = re.fullmatch(r"я пришлю тебе (.+)", lowered)
        if promise:
            return Interpretation(source_version_id=context.source_version_id, operation="create", kind="waiting",
                                  title="Дождаться: " + promise.group(1), obvious=True)
        if lowered.startswith(("пожалуйста", "надо", "проверь", "сделай")):
            return question(context, "Кому адресована просьба и кто должен её выполнить?")
    return None
