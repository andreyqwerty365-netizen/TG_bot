from io import BytesIO

from PIL import Image, ImageDraw

from bot.services.schedule_image import parse_shift_colors


def test_parse_shift_colors_reads_day_night_and_off_cells():
    days = 5
    cell_width = 24
    image = Image.new("RGB", (20 + days * cell_width + 30, 70), "white")
    draw = ImageDraw.Draw(image)
    for index in range(days + 1):
        x = 20 + index * cell_width
        draw.line((x, 0, x, 69), fill="black", width=2)
    colors = ["white", "red", "blue", "white", "red"]
    for index, color in enumerate(colors):
        draw.rectangle((22 + index * cell_width, 42, 18 + (index + 1) * cell_width, 67), fill=color)
    output = BytesIO()
    image.save(output, format="PNG")

    assert parse_shift_colors(output.getvalue(), days) == ["off", "day", "night", "off", "day"]
