from __future__ import annotations

from io import BytesIO
from statistics import mean

from PIL import Image, UnidentifiedImageError


def parse_shift_colors(image_bytes: bytes, days_in_month: int) -> list[str]:
    if not 1 <= days_in_month <= 31:
        raise ValueError("Некорректное число дней в месяце.")
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Не удалось прочитать изображение.") from exc
    width, height = image.size
    if width < days_in_month * 6 or height < 20:
        raise ValueError("Изображение графика слишком маленькое.")

    pixels = image.load()
    separator_groups: list[list[int]] = []
    current: list[int] = []
    for x in range(width):
        dark = sum(1 for y in range(height) if max(pixels[x, y]) < 75)
        if dark / height >= 0.7:
            current.append(x)
        elif current:
            if len(current) <= 5:
                separator_groups.append(current)
            current = []
    if current and len(current) <= 5:
        separator_groups.append(current)

    separators = [round(mean(group)) for group in separator_groups]
    best: tuple[float, list[int]] | None = None
    for index in range(len(separators) - days_in_month):
        candidate = separators[index : index + days_in_month + 1]
        gaps = [right - left for left, right in zip(candidate, candidate[1:])]
        average = mean(gaps)
        if not 6 <= average <= 100:
            continue
        deviation = max(abs(gap - average) for gap in gaps) / average
        if deviation <= 0.2 and (best is None or deviation < best[0]):
            best = (deviation, candidate)
    if best is None:
        raise ValueError("Не нашёл сетку с днями месяца.")

    boundaries = best[1]
    shifts: list[str] = []
    for left, right in zip(boundaries, boundaries[1:]):
        red = blue = total = 0
        for x in range(left + 2, right - 1):
            for y in range(height):
                r, g, b = pixels[x, y]
                total += 1
                if r > 150 and r > g * 1.7 and r > b * 1.7:
                    red += 1
                elif b > 120 and b > r * 1.5 and b > g * 1.25:
                    blue += 1
        minimum = max(3, int(total * 0.04))
        if red >= minimum and red > blue:
            shifts.append("day")
        elif blue >= minimum:
            shifts.append("night")
        else:
            shifts.append("off")
    return shifts
