# Personal CRM — первое проверяемое ядро

Изолированный модуль в `personal-crm/`. Реализованы FastAPI, PostgreSQL/Alembic, источники с версиями, задачи/ожидания/заметки, предложения, история и постоянная очередь с fake-доставкой. Существующий Telegram-бот и производственное развёртывание не меняются.

Интерпретатор понимает только контролируемые синтетические fixtures из `fixtures/demo.json`. Любой другой текст сохраняется и получает уточнение. Это не полноценный разбор русской речи. Настоящие Telegram, почта и OpenAI не подключены; `real_ai()` всегда закрывает доступ к внешнему провайдеру.

## Установка и тестовая PostgreSQL

Все команды выполняются из `personal-crm/`. Проверено на Linux amd64, Python 3.12, PostgreSQL 16.10, Docker 28.4.0. Нужен отдельный disposable PostgreSQL для тестов; тесты очищают его схему и требуют имя `personal_crm_test*` и отдельную переменную `CRM_TEST_DATABASE_URL`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
docker run --name personal-crm-test-pg \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER=crm_test \
  -e POSTGRES_DB=personal_crm_test -p 127.0.0.1:55432:5432 -d postgres:16.10
# Дождаться: docker exec personal-crm-test-pg pg_isready -U crm_test
export CRM_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test
.venv/bin/alembic upgrade head
export CRM_TEST_DATABASE_URL="$CRM_DATABASE_URL"
.venv/bin/python -m pytest -q
.venv/bin/python -m personal_crm.demo
```

Trust используется только для отдельной локальной тестовой БД с портом на loopback. Compose использует пароль. При уже существующем тестовом контейнере запустить его вместо повторного создания. Не задавать production URL тестам. Миграции тестируются вниз/вверх только на disposable БД; откат схемы удаляет данные.

Демо не очищает БД, создаёт новый синтетический профиль для каждого запуска и ограничивает worker этим профилем. Оно запускает отдельные процессы чтения и доставки. Ожидаемый вывод:

```text
new process: source, task and two history records persisted
fake worker outcome=sent
{"source_persisted": true, "duplicate_applied_once": true, "fake_delivery_attempts": 1, "closed_repeat_cancelled": true, "mail_proposal_confirmed": true, "real_external_calls": 0}
```

## API и фоновый процесс без Docker

Задать `CRM_OWNER_ID` как локальный синтетический идентификатор, `CRM_OWNER_TOKEN` как отдельный credential API, `CRM_FAKE_MAIL_TOKEN` как credential fake-mail и `CRM_TIMEZONE` как явно выбранный IANA-пояс. Пустая настройка владельца закрывает доступ; пустой пояс запрещает календарные автоматические уведомления. Секреты не передаются в JSON владельца и не выводятся в диагностике. Не использовать токен действующего Telegram-бота.

```bash
.venv/bin/uvicorn personal_crm.api:create_app --factory --host 127.0.0.1 --port 8001
# В другом терминале с тем же CRM_DATABASE_URL:
.venv/bin/python -m personal_crm.worker
```

Защищённые запросы требуют `Authorization: Bearer <CRM_OWNER_TOKEN>`. API: `POST /sources` с account, external_id, text, revision и channel=owner/forward; `GET /sources`, `GET /tasks`, `GET /proposals`; `POST /sources/{source_version_id}/retry`; `POST /tasks/{task_id}/commands` с version и action=close/reminder/deadline/title; `POST /proposals/{proposal_id}/confirm` с version и accept. Fake-mail использует отдельный `X-Connector-Token`, принимает только mail-источники и не может подтверждать предложения. Вводить owner_id в запросах нельзя. `GET /health` проверяет процесс, `/ready` — настройки владельца, подключение и схему. Моменты напоминаний должны содержать timezone; дедлайн сохраняет точность date/instant и исходную формулировку.

## Отдельный Docker Compose

Скопировать `.env.example` в `.env` и заполнить только локальными данными. `CRM_DATABASE_URL` внутри Compose имеет вид `postgresql+psycopg://crm:<URL-encoded local password>@crm-db:5432/personal_crm`. Значение пароля должно совпадать с `CRM_DB_PASSWORD`. Секреты в шаблоне пустые. Не коммитить `.env`.

В облачной среде Docker не разрешал DNS для PyPI. Повторяемый путь сборки загружает wheels через Python среды с нормальной TLS-проверкой и затем монтирует их только на время сборки. Docker проверяет SHA256SUMS и устанавливает зависимости без сети. Нужен Docker BuildKit и Compose с additional_contexts; wheels готовить для Python 3.12 той же платформы, что образ.

```bash
.venv/bin/python scripts/prepare_wheels.py
docker compose --env-file .env build
docker compose --env-file .env up -d
# Для прямой сборки:
docker build --build-context crm_wheels=.runtime/wheels -t personal-crm:dev .
```

Сервисы `crm-db`, `crm-migrate`, `crm-api`, `crm-worker` используют отдельный volume `personal-crm_crm-postgres`; API доступен только на loopback порта 8001. Миграции завершаются до API/worker. Worker отправляет исключительно в fake-транспорт. Для проверки работающего стека из хоста задать owner credentials, `CRM_API_BASE` при другом порте и хостовый `CRM_DATABASE_URL` (127.0.0.1:55433 вместо crm-db:5432), затем:

```bash
.venv/bin/python scripts/smoke_http.py
```

Ожидается `HTTP smoke passed: readiness, owner auth, source, reminder, background fake delivery, close/cancel`. `docker compose down` останавливает сервисы, сохраняя volume; не добавлять `-v`, если данные нужны. При ограничении HOME на запись использовать `DOCKER_CONFIG="$PWD/.runtime/docker"` для команд Docker; не копировать туда найденные credentials.

## Что проверено и что осталось

Фактические результаты и соответствия R/D/T/O-T записаны в `docs/ACCEPTANCE.md`; прогресс и решения — в `EXECPLAN.md`, аудит — в `docs/LEGACY_AUDIT.md`. Тесты используют настоящую PostgreSQL, не SQLite. Корневой pytest остаётся отдельным (133 теста бота); CRM имеет собственное окружение и конфигурацию сбора.

Уведомления: максимум две инициативы за локальные сутки и интервал не меньше четырёх часов, точные команды вне лимита, один автоматический повтор; есть непустая сводка до трёх активных дел и число предложений. Молчание не меняет состояние, постороннее сообщение не отменяет повтор. Журнал доставки сохраняет идентификаторы и исход, не текст. При неопределённом исходе автоматические попытки прекращаются. Захват имеет lease/fencing; блокировка владельца сериализует команды и отправку. Future network transport обязан иметь timeout короче lease; сейчас транспорт только fake.

Остались: полноценная интерпретация русского ввода и привязка разговорных ответов, Telegram-приёмник, почтовая синхронизация и хранение/очистка писем, Responses/Structured Outputs с реальным конкурентным бюджетным шлюзом, React, шаги/регулярность/планирование/адаптация, выбор забытых дел и сообщение о просрочке, пакетная обработка накопленных опоздавших точных уведомлений после долгого простоя, резервирование/восстановление, импорт копий legacy и production-пилот. Текущий worker проверяет версии и отмены, но ещё не объединяет большой просроченный backlog в отчёт. Промышленная готовность не заявляется.
