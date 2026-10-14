def short_reply(result):
    status = result["status"]
    if status == "created":
        return "Дело сохранено: " + result["task"]["title"][:240] + "."
    if status == "changed":
        return "Дело выполнено." if result["task"]["state"] == "done" else "Изменение сохранено."
    if status == "accepted":
        return "Предложение принято, изменение сохранено."
    if status == "rejected":
        return "Предложение отклонено."
    if status == "proposal":
        proposed = result.get("proposal", {})
        action = {"close": "выполнить", "reminder": "изменить напоминание", "plan": "изменить план",
                  "deadline": "изменить дедлайн", "title": "изменить название"}.get(proposed.get("change"), "создать дело")
        details = result.get("target_title", "")[:180]
        if proposed.get("reminder_at"):
            details += "; напоминание " + proposed["reminder_at"]
        if proposed.get("deadline"):
            deadline = proposed["deadline"]
            details += f"; срок {deadline['value']} ({deadline['precision']}, {deadline['timezone']})"
        if proposed.get("planned_on"):
            details += "; план " + proposed["planned_on"]
        if proposed.get("return_on"):
            details += "; вернуться " + proposed["return_on"]
        if proposed.get("focused") is not None:
            details += "; фокус " + ("да" if proposed["focused"] else "нет")
        if proposed.get("change") == "title":
            details += "; новое название " + proposed.get("title", "")[:180]
        if proposed.get("change") in ("defer", "resume", "cancel", "focus"):
            action = {"defer": "отложить дело", "resume": "вернуть дело", "cancel": "отменить дело", "focus": "изменить фокус"}[proposed["change"]]
        return f"Предлагаю {action}: {details}. Подтверждаете? Ответьте на это сообщение «да» или «нет»."
    if status == "clarification":
        return "Сообщение сохранено. " + result.get("question", "Уточните действие.")[:500]
    if status == "conflict":
        return "Дело уже изменилось. Уточните актуальное действие; старое подтверждение не применено."
    if status == "overview":
        from .accompaniment import render_overview
        return (render_overview(result["overview"]) or "На сегодня сохранённых дел нет.")[:3500]
    return "Сообщение сохранено. Разбор пока не завершён; задача не создана этим ответом."
