# Personal CRM — ядро и сопровождение задач

Изолированный модуль в `personal-crm/`. Реализованы FastAPI, PostgreSQL/Alembic, источники с версиями, задачи/ожидания/заметки, предложения, история, постоянная очередь с fake-доставкой и детерминированное сопровождение задач. Существующий Telegram-бот и производственное развёртывание не меняются.

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
.venv/bin/python -m personal_crm.simulation
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

Защищённые запросы требуют `Authorization: Bearer <CRM_OWNER_TOKEN>`. API: `POST /sources` с account, external_id, text, revision и channel=owner/forward; `GET /sources`, `GET /tasks`, `GET /proposals`, `GET /overview`, `GET /guidance`, `GET /deliveries`; `GET /tasks/{task_id}/history`; `POST /sources/{source_version_id}/retry`; `POST /tasks/{task_id}/commands` с version и action=close/reminder/deadline/title/plan/defer/resume/cancel/focus; `POST /proposals/{proposal_id}/confirm` с version и accept. Fake-mail использует отдельный `X-Connector-Token`, принимает только mail-источники и не может подтверждать предложения. Вводить owner_id в запросах нельзя. `GET /health` проверяет процесс, `/ready` — настройки владельца, подключение и схему. Моменты напоминаний должны содержать timezone; дедлайн сохраняет точность date/instant и исходную формулировку.

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

Ожидается `HTTP smoke passed: readiness, owner auth, source, reminder, background fake delivery, close/cancel, plan, overview, history`. `docker compose down` останавливает сервисы, сохраняя volume; не добавлять `-v`, если данные нужны. При ограничении HOME на запись использовать `DOCKER_CONFIG="$PWD/.runtime/docker"` для команд Docker; не копировать туда найденные credentials.

## Что проверено и что осталось

Фактические результаты и соответствия R/D/T/O-T записаны в `docs/ACCEPTANCE.md`; прогресс и решения — в `EXECPLAN.md`, аудит — в `docs/LEGACY_AUDIT.md`. Тесты используют настоящую PostgreSQL, не SQLite. Корневой pytest остаётся отдельным (133 теста бота); CRM имеет собственное окружение и конфигурацию сбора.

Уведомления: максимум две инициативы за локальные сутки и интервал не меньше четырёх часов, точные команды вне лимита, один автоматический повтор; есть непустая сводка с тремя главными делами, ближайшими сроками, ротацией двух забытых дел, ожиданиями, предложениями и одноразовыми вопросами. Молчание не меняет состояние, постороннее сообщение не отменяет повтор. Журнал доставки сохраняет идентификаторы и исход, не текст. При неопределённом исходе автоматические попытки прекращаются. Захват имеет lease/fencing; блокировка владельца сериализует команды и отправку. Future network transport обязан иметь timeout короче lease; сейчас транспорт только fake.

Остались: полноценная интерпретация русского ввода и привязка разговорных ответов, Telegram-приёмник, почтовая синхронизация/retention, Responses/Structured Outputs с реальным конкурентным бюджетным шлюзом, React, подшаги/регулярность/адаптация и настройки через интерфейс, предложения раннего выполнения, резервирование/восстановление, импорт копий legacy и production-пилот. Промышленная готовность не заявляется.

## Сопровождение и симуляция четырёх недель

`plan` принимает `planned_on` (календарную дату выполнения), `defer` — будущую `return_on`, `focus` — boolean `focused`. `resume` досрочно возвращает отложенное дело, `cancel` явно отменяет. Все команды проверяют владельца и version, сохраняют историю и не меняют дедлайн/время уведомления вместо указанного поля. При отсутствии пояса календарные команды блокируются. Возврат по заданной дате выполняется детерминированно, записывается в history и не оживляет старые отправки. Смена плана отменяет устаревший автоматический repeat, сохраняя явное точное уведомление.

Переносом считается более поздняя дата после уже заданного плана. Первичное планирование, та же/более ранняя дата, перенос reminder и молчание счётчик не увеличивают. После каждых трёх таких переносов появляется один вопрос о препятствии с вариантами действий. Он не закрывает, не откладывает и не дробит задачу самостоятельно. Модель может только предложить изменение плана; подтверждение проверяет текущую версию.

`GET /overview` возвращает main (до трёх), все deadlines с вычисляемой просрочкой, forgotten (до двух), waiting, proposals, guidance и missed_reminders. Порядок main: выбранный фокус, ближайшие предстоящие сроки, просрочки, план сегодня, забытые дела. Полный ответ сохраняет все сроки; компактное сообщение перечисляет ближайшие три и число остальных. Ротация учитывает последнее успешное представление и обсуждение владельцем. Представление не означает прочтение; ручной обзор не расходует лимит и не меняет ротацию.

Дата без времени становится просроченной только на следующую календарную дату её явно сохранённого пояса. Точный момент сравнивается с UTC. Одно предупреждение для согласованного срока попадает в инициативу либо сводку при исчерпанном лимите. Новый план выполнения не стирает просрочку и не запускает новое одинаковое предупреждение. Неопределённый исход доставки не объявляется успешным и не вызывает слепое повторение предупреждения в сводке. История guidance доступна отдельно, включая sent/unknown/stale/resolved.

`Profile.catchup_grace_seconds` задаёт порог опоздания (по умолчанию 3600). Более старые точные jobs сохраняются как cancelled с `missed_after_outage` и объединяются в один отчёт. Обязательства не удаляются и не завершаются. Напоминание внутри порога позднее минуты явно обозначается как опоздавшее. Закрытие/откладывание или новое расписание перед отправкой делают старый отчёт неактуальным. Незавершённая попытка с возможной доставкой восстанавливается как unknown, включая случай последующей отмены job, и не классифицируется как определённый пропуск.

Команда `.venv/bin/python -m personal_crm.simulation` создаёт уникальный синтетический профиль, использует настоящую PostgreSQL и управляемые часы, включая сезонную смену времени. Каждый день создаётся новый объект worker; реальных четырёх недель ждать не нужно. Проверенный вывод:

```json
{"simulated_days": 28, "daily_digests": 28, "forgotten_tasks_presented": 13, "overdue_announcements": 1, "obstacle_questions": 1, "missed_jobs_consolidated": 3, "automatic_completions": 0, "real_external_calls": 0}
```

Фактически пройдены **69 тестов CRM** на PostgreSQL, включая 28-дневную ротацию, конкуренцию, даты, переносы, неопределённость и миграцию с сохранением существующих записей. Один известный DeprecationWarning Starlette/AnyIO. **133 теста legacy-бота** также прошли. Начальная миграция сохранена, дополнение — `9b0fd1794927_task_accompaniment`; `alembic upgrade head` применяет её без очистки данных. Downgrade удаляет добавленные поля/таблицы и проверяется только на disposable test DB. Любая будущая production-миграция требует отдельной процедуры и не выполнялась.
