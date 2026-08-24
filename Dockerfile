FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV BOT_DB_PATH=/data/notes.db
ENV BOT_LOG_PATH=/data/logs/bot.log
ENV BOT_INTERACTION_LOG_PATH=/data/logs/interactions.log
ENV BOT_TRAINER_DB_PATH=/data/workouts.sqlite3
ENV BOT_EXERCISES_PATH=/app/exercises.json

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY . .
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /data \
    && chown -R bot:bot /data

USER bot

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "tools/healthcheck.py", "--db", "/data/notes.db"]

CMD ["python", "main.py"]
