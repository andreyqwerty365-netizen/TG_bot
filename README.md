# Telegram Assistant: секретарь и тренер

Личный Telegram-бот с двумя отдельными разделами: секретарь для заметок и напоминаний и персональный тренер для дневника занятий.

## Возможности

- быстрый ввод одной строкой;
- план на сегодня;
- архив заметок и напоминаний;
- повторы `/every day`, `/every week`, `/every month`;
- поиск по заметкам и напоминаниям;
- экспорт и импорт JSON;
- локальный лог в `logs/bot.log`.

Раздел «Тренер» умеет:

- записывать силовые упражнения с 1–3 подходами по схеме 12 / 10 / 8;
- сохранять базовые и последние рабочие веса;
- записывать ходьбу на дорожке по дистанции;
- показывать изображения упражнений и историю занятий;
- экспортировать тренировки в Excel.

## Быстрый запуск на Windows

1. Скопируй `.env.example` в `.env`.
2. Впиши `BOT_TOKEN`. Оставь `BOT_ALLOWED_USER_IDS` пустым для открытого доступа.
3. Запусти `run.bat`.

Если `.env` ещё нет, `run.bat` создаст шаблон и попросит ввести токен. Пустой `BOT_ALLOWED_USER_IDS` разрешает пользоваться ботом всем; чтобы снова закрыть доступ, перечисли разрешённые Telegram user ID через запятую.

## Запуск вручную

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Команды

- `/start` — главное меню
- `/today` — план на сегодня
- `/last` — последние записи
- `/new` — быстрый ввод
- `/notes` — последние заметки
- `/reminders` — активные напоминания
- `/search <текст>` — поиск
- `/settings` — настройки
- `/tz` — таймзона
- `/export` — экспорт JSON
- `/import` — импорт JSON
- `/trainer` — меню персонального тренера
- `/workout` — записать тренировку
- `/workout_history` — история тренировок
- `/workout_export` — экспорт тренировок в Excel
- `/cancel` — отменить текущий ввод тренировки

## Локальные файлы

- `notes.db` — SQLite база
- `workouts.sqlite3` — отдельная SQLite база тренировок
- `logs/bot.log` — лог запуска и ошибок
- `backups/` — резервные копии базы

## Docker

```bash
docker build -t telegram-bot-pro .
docker run --rm --env-file .env telegram-bot-pro
```

## Тесты

```powershell
.venv\Scripts\python.exe tools\run_tests.py -q
.venv\Scripts\python.exe tools\check_no_secrets.py
.venv\Scripts\python.exe tools\production_preflight.py
```

## Сборка EXE

Для Windows-сборки используется `build_exe.bat`.

## Безопасность токена

Храни реальный `BOT_TOKEN` только в локальном `.env` или в `.env.vps` на сервере. Эти файлы исключены из Git и Docker-контекста. После утечки токена немедленно перевыпусти его через BotFather и перезапусти бот.

Новые логи ротируются и не должны содержать Bot API token, Telegram user ID, chat ID, тексты заметок, тексты напоминаний или имена загруженных файлов. UX-журнал `logs/interactions.log` хранит только обезличенные действия, режимы, id записей и результаты.

## Постоянный запуск на Linux VPS

На VPS нужны Docker с Compose plugin, `restic` и Python 3. Репозиторий размещается в `/opt/telegram-assistant`.

```bash
cd /opt/telegram-assistant
cp .env.vps.example .env.vps
mkdir -p data/logs data/backups
sudo chown -R 10001:10001 data
chmod +x deploy/*.sh
```

Заполни `.env.vps` новым токеном до запуска. Оставь `BOT_ALLOWED_USER_IDS` пустым для открытого доступа или перечисли разрешённые Telegram user ID через запятую. SQLite будет храниться в `data/notes.db`, внутри контейнера это `/data/notes.db`.

## Внешние резервные копии

Скопируй примеры секретов вне репозитория и заполни их:

```bash
sudo mkdir -p /etc/telegram-assistant
sudo cp deploy/restic.env.example /etc/telegram-assistant/restic.env
sudo cp deploy/alert.env.example /etc/telegram-assistant/alert.env
sudo chmod 600 /etc/telegram-assistant/*.env
deploy/preflight.sh
docker compose up -d --build
docker compose ps
set -a; source /etc/telegram-assistant/restic.env; set +a
restic init
deploy/backup_to_s3.sh
deploy/verify_restore.sh
```

`deploy/preflight.sh` проверяет наличие Docker Compose, `restic`, Python 3, заполненных env-файлов и владельца `10001` у каталогов `data`, `data/logs`, `data/backups` без вывода секретов. `deploy/backup_to_s3.sh` создаёт консистентный SQLite snapshot через online backup API, отправляет его в зашифрованное S3-совместимое хранилище и выполняет ротацию. Пример расписания находится в `deploy/crontab.example`.

Проверка восстановления:

```bash
deploy/verify_restore.sh
```

Для обновления:

```bash
cd /opt/telegram-assistant
deploy/backup_to_s3.sh
git pull
deploy/preflight.sh
docker compose up -d --build
docker compose ps
docker compose exec -T bot python tools/healthcheck.py --db /data/notes.db
```

Сначала создаётся внешний зашифрованный backup текущей базы. После обновления `deploy/preflight.sh` проверяет конфигурацию и существующую SQLite-базу, а финальный healthcheck подтверждает состояние базы уже внутри нового контейнера.
