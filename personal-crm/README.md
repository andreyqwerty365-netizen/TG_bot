# Personal CRM — дела, веб-интерфейс и сопровождение

Подготовка первого личного запуска: сохранённый вход по паролю, быстрый ввод с уточнением, operational статус и opt-in encrypted S3 publication. [Размещение на VPS](docs/PILOT_DEPLOYMENT.md), [первые пять действий](docs/USER_GUIDE.md). Текущие проверки и ограничения — [ACCEPTANCE.md](docs/ACCEPTANCE.md); следующие шаги — [EXECPLAN_PILOT.md](EXECPLAN_PILOT.md). Реальная инфраструктура и аккаунты ещё не подключены.

Резервирование и перенос: [RECOVERY.md](docs/RECOVERY.md). Добавлены AES-256-GCM PostgreSQL копии, ежедневный opt-in цикл/30-дневное хранение, восстановление только в пустую isolated базу с блокировкой отправок, внешний журнал удаления профилей, readonly rehearsal импорта SQLite и экспорт из настроек веба. Внешний носитель и production-перенос не настроены; реальный ящик по-прежнему отключён.

Адаптивное приложение на React + TypeScript использует тот же FastAPI/PostgreSQL, что Telegram-ввод и постоянная очередь. Работают Сегодня, Все дела, Входящие, Проекты и Настройки: создание произвольных ручных задач без ИИ, поиск/фильтры/страницы, редактирование отдельных календарных полей, состояния, история, подтверждения и ответы на уточнения. Настройки пояса, сводки, инициатив, паузы ИИ и уменьшения бюджета сохраняются в PostgreSQL. Клиент не хранит отдельную базу задач; секреты интеграций в него не передаются.

## Запуск веба

Из `personal-crm/web/`, Node.js 24:

    npm ci
    npm run build
    npm test

Из `personal-crm/`, с локальными переменными `CRM_DATABASE_URL`, `CRM_OWNER_ID`, `CRM_OWNER_TOKEN`, `CRM_TIMEZONE`:

    .venv\Scripts\python.exe -m alembic upgrade head
    .venv\Scripts\python.exe -m uvicorn personal_crm.api:create_app --factory --host 127.0.0.1 --port 8001

Открыть `http://127.0.0.1:8001/app/` и ввести пароль, hash которого задан в `CRM_WEB_PASSWORD_HASH`; для localhost явно нужны `CRM_WEB_ORIGIN=http://127.0.0.1:8001` и `CRM_WEB_INSECURE_LOCALHOST=true`. Hash получить `python -m personal_crm.pilot_setup password-hash`. На Linux использовать `.venv/bin/python`. Для непрерывного разбора отдельно запустить `personal_crm.source_worker`; настоящая доставка включается отдельно. Подробности разработки и синтетической E2E-базы — `web/README.md`. Development Dockerfile копирует готовый `web/dist`; Dockerfile.production собирает React сам.

Итоговый полный прогон: **165 CRM tests**, **133 legacy tests**, **3 React unit tests**, **8 browser E2E scenarios** на desktop/mobile. Проверены owner scope, конфликты, транзакции, миграции, браузерные защитные заголовки и отсутствие поискового текста в HTTP-журнале. TypeScript/build, core/Stage 2 demo и 28-дневная симуляция прошли. PostgreSQL настоящая, внешние продуктовые вызовы выключены. Docker на этой машине отсутствует: обновлённая сборка образа Not Run.

## Продолжение: критические исправления

Ветка `codex/personal-crm-reliability-web` сохраняет предыдущую Stage 2. Отрицания и вопросы о выполнении не завершают задачу. Уточнение времени принимает «в 19:00» и сохраняет уже разрешённую дату через перезапуск/полночь. Именованная старая задача и постоянные ссылки находятся запросом ко всей БД; лимит контекста модели не ограничивает поиск. Правка названия и времени источника создаёт подтверждаемое предложение и применяет оба поля одной транзакцией.

Аддитивная миграция `b63125ff910a` добавляет постоянный счётчик обработки и время следующего повтора. Отдельный процесс подбирает сохранённые pending-источники, просроченные parse leases и временные ошибки с задержкой. При обычной временной ошибке максимум три автоматические попытки (60/120 секунд); исходник остаётся доступен для явного retry. Timeout и неопределённо оплаченный вызов OpenAI автоматически не повторяются. Достоверный неоплаченный отказ освобождает резерв и допускает явный повтор с новой проверкой лимита; HTTP 429 имеет ограниченный автоматический повтор.

Запустить вместе с API и worker, из `personal-crm/`, с теми же локальными `CRM_DATABASE_URL`, `CRM_OWNER_ID`, `CRM_OWNER_TOKEN`, `CRM_TIMEZONE`:

    .venv\Scripts\python.exe -m alembic upgrade head
    .venv\Scripts\python.exe -m personal_crm.source_worker

На Linux заменить `.venv\Scripts\python.exe` на `.venv/bin/python`. `--once` выполняет один проход. Compose включает `crm-source-worker`; его ошибки не блокируют доставку напоминаний. Все внешние enable-флаги остаются false.

На отдельной PostgreSQL 16.10/Windows/Python 3.12: **145 passed**, одно прежнее Starlette/AnyIO предупреждение. Включены 21 новый сценарий, migration down/up/check, core/Stage 2 demo и 28-дневная симуляция. Независимая оценка GPT, настоящие Telegram/почта, Docker Compose на этой машине и production не запускались. Текущее состояние и дальнейшие этапы — `EXECPLAN_CONTINUATION.md`.

Изолированный модуль в `personal-crm/`. Реализованы FastAPI, PostgreSQL/Alembic, источники с версиями, задачи/ожидания/заметки, предложения, история, постоянная очередь с fake-доставкой и детерминированное сопровождение задач. Существующий Telegram-бот и производственное развёртывание не меняются.

Stage 2 поддерживает ограниченную грамматику очевидных русских команд, постоянные уточнения/подтверждения, синтетические Telegram Updates и опциональный OpenAI Responses adapter с PostgreSQL-бюджетом. Неизвестная фраза при выключенной модели сохраняется с честным статусом незавершённого разбора. Telegram webhook/отправка и OpenAI выключены по умолчанию; реальных вызовов при проверке не было. Произвольный русский текст и качество GPT не объявлены проверенными.

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
.venv/bin/python -m personal_crm.stage2_demo
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

Сервисы `crm-db`, `crm-migrate`, `crm-api`, `crm-worker` используют отдельный volume `personal-crm_crm-postgres`; API доступен только на loopback порта 8001. Миграции завершаются до API/worker. По умолчанию worker отправляет в fake-транспорт; отдельный test-bot transport требует явной конфигурации и включения. Для проверки работающего стека из хоста задать owner credentials, `CRM_API_BASE` при другом порте и хостовый `CRM_DATABASE_URL` (127.0.0.1:55433 вместо crm-db:5432), затем:

```bash
.venv/bin/python scripts/smoke_http.py
```

Ожидается `HTTP smoke passed: readiness, owner auth, source, reminder, background fake delivery, close/cancel, plan, overview, history`. `docker compose down` останавливает сервисы, сохраняя volume; не добавлять `-v`, если данные нужны. При ограничении HOME на запись использовать `DOCKER_CONFIG="$PWD/.runtime/docker"` для команд Docker; не копировать туда найденные credentials.

## Что проверено и что осталось

Фактические результаты и соответствия R/D/T/O-T записаны в `docs/ACCEPTANCE.md`; прогресс и решения — в `EXECPLAN.md`, аудит — в `docs/LEGACY_AUDIT.md`. Тесты используют настоящую PostgreSQL, не SQLite. Корневой pytest остаётся отдельным (133 теста бота); CRM имеет собственное окружение и конфигурацию сбора.

Уведомления: максимум две инициативы за локальные сутки и интервал не меньше четырёх часов, точные команды вне лимита, один автоматический повтор; есть непустая сводка с тремя главными делами, ближайшими сроками, ротацией двух забытых дел, ожиданиями, предложениями и одноразовыми вопросами. Молчание не меняет состояние, постороннее сообщение не отменяет повтор. Журнал доставки сохраняет идентификаторы и исход, не текст. При неопределённом исходе автоматические попытки прекращаются. Захват имеет lease/fencing; блокировка владельца сериализует команды и отправку. Test-bot transport соблюдает ограниченные тайм-ауты короче lease; все проверки выполнены с fake/mocked транспортом.

Остались: независимая оценка произвольного русского ввода и реальной модели, испытание внешних Telegram/OpenAI каналов с отдельным разрешением, почтовая синхронизация/retention, расширенная регулярность/адаптация, предложения раннего выполнения, encrypted backup/restore, импорт копий legacy и production-пилот. Веб и редактируемые настройки реализованы в продолжении; разговорные ответы, Telegram adapter, текстовые подшаги и конкурентный бюджетный шлюз — в Stage 2. Промышленная готовность не заявляется.

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

В предыдущем этапе фактически пройдены **69 тестов CRM** на PostgreSQL, включая 28-дневную ротацию, конкуренцию, даты, переносы, неопределённость и миграцию с сохранением существующих записей. Один известный DeprecationWarning Starlette/AnyIO. **133 теста legacy-бота** также прошли. Начальная миграция сохранена, дополнение — `9b0fd1794927_task_accompaniment`; `alembic upgrade head` применяет её без очистки данных. Downgrade удаляет добавленные поля/таблицы и проверяется только на disposable test DB. Любая будущая production-миграция требует отдельной процедуры и не выполнялась.

## Stage 2: синтетический Telegram и русский ввод

Для HTTP-сценария задать только вымышленные allowlists: `CRM_TELEGRAM_BOT_ID=303`, `CRM_TELEGRAM_ALLOWED_USER_IDS=101`, `CRM_TELEGRAM_ALLOWED_CHAT_IDS=202`. Это тестовые идентификаторы, не настоящий бот. Добавить их в локальный .env перед запуском Compose. Реальные enable-флаги остаются false. После запуска API/worker с тем же PostgreSQL и owner credential:

```bash
.venv/bin/python scripts/smoke_http.py
.venv/bin/python scripts/smoke_stage2_http.py
```

Smoke из хоста требует хостовый CRM_DATABASE_URL на 127.0.0.1:55433, CRM_OWNER_ID/TOKEN и CRM_TIMEZONE из локальной конфигурации, CRM_API_BASE при другом порте. Он не печатает credentials. POST `/adapters/synthetic-telegram` защищён Bearer owner token и принимает стандартную форму Update. Пример полностью синтетического тела:

```json
{"update_id":1,"message":{"message_id":1,"date":1791878400,"from":{"id":101,"is_bot":false},"chat":{"id":202,"type":"private"},"text":"Завтра в 19:00 напомни обновить резюме"}}
```

Простые поддержанные фразы: «Завтра в 19:00 напомни обновить резюме», «Надо добавить игровой клуб в портфолио», «Резюме обновил», «Последнее выполнил», «Выполнил задачу», «Перенеси напоминание на завтра», «Перенеси последнее напоминание на субботу», «Перенеси план/дедлайн на 2026-10-23», «Что на сегодня?». Напоминание использует явно заданный пояс профиля. При переносе без часов сохраняются часы существующего reminder, дедлайн не меняется. Поддержаны сегодня/завтра/послезавтра, ближайший явно названный день недели и ISO-дата с HH:MM. «До пятницы», «23 числа», отсутствующий пояс, одинаковый день недели и DST gap/fold требуют уточнения. Это ограниченная грамматика, а не универсальный NLP.

Пересылка «Я пришлю тебе договор» создаёт waiting, просьба с неизвестным адресатом или старая относительная дата вызывает вопрос. Mail формирует предложения. Reply к входящему источнику или успешно записанному исходящему сообщению связывает ответ с владельцем/account/source. «Да/нет» адресует конкретный proposal version, дата — pending_action/task version. Вопрос живёт 24 часа и переживает новый процесс; несвязанная новая фраза, включая ошибку разбора, отключает неявную привязку к старому вопросу. Явный reply остаётся доступным до истечения срока. Ответы выдаются через постоянную reply-очередь после commit; unknown доставки не повторяется вслепую. Голос/файл не анализируется, caption рассматривается только как текст.

CLI `.venv/bin/python -m personal_crm.stage2_demo` создаёт уникальный синтетический профиль, не очищает БД, использует управляемые часы и новый service/engine для проверки сохранённого диалога. Ожидаемый итог: synthetic_updates/direct_exact_reminder/duplicate_applied_once/dialogue_survived_new_service/completion_cancelled_repeat=true, fake_replies=7, fake_exact_delivery=1, real_external_calls=0.

## Опциональные внешние адаптеры: конфигурация и границы

Все placeholders в .env.example пустые, кроме безопасных лимитов/выключенных флагов. Здесь нет реального включения, polling или установки webhook. `/telegram/webhook` возвращает 404 при выключенном CRM_TELEGRAM_WEBHOOK_ENABLED, затем проверяет constant-time CRM_TELEGRAM_WEBHOOK_SECRET и фактические user/chat allowlists. Группы требуют CRM_TELEGRAM_ALLOW_GROUPS. Sender требует отдельного CRM_TELEGRAM_TEST_TOKEN, CRM_TELEGRAM_SEND_ENABLED, server bot ID, разрешённого outbound chat и сверки getMe. Рабочий BOT_TOKEN не читается. Будущее объединение с действующим ботом — через один update consumer и согласованный sender, без второго production polling/webhook.

Responses использует официальный SDK openai==3.31.0 и strict Pydantic Structured Outputs, store=false и zero retries. Настройка требует одновременно CRM_OPENAI_ENABLED, серверный OPENAI_API_KEY, конкретный CRM_OPENAI_MODEL в CRM_OPENAI_ALLOWED_MODELS, согласие CRM_AI_CONSENT_CATEGORIES для нужных категорий owner/forward/mail/tasks/dialog, положительный CRM_OPENAI_MONTHLY_BUDGET_USD и действующий CRM_OPENAI_PRICES_JSON. Ни один SDK-клиент не создаётся до этих проверок. Реальные значения ключа/модели/тарифа в репозитории не заданы.

Таблица цен — JSON object с ключом выбранной модели. Поля: currency (USD), source (HTTPS-источник проверенного тарифа), valid_until (будущий ISO-момент с поясом), input_per_million/output_per_million (положительные USD), input_token_ceiling (доверенный полный верхний предел model input). Цена не берётся из примера и не угадывается. Верхняя резервация = ceiling × input price + max_output × output price в micro-USD; текущий payload + схема/протокол проверяются консервативной byte-границей. Такая защита может отказать до полного расхода бюджета. Настройки лимитов: CRM_OPENAI_MAX_INPUT_CHARS=8000, CRM_OPENAI_MAX_OUTPUT_TOKENS=512, CRM_OPENAI_TIMEOUT_SECONDS=8. HTTP ограничен размером и временем, не наследует произвольный OPENAI_BASE_URL или организацию проекта из окружения.

`GET /ai/status` под owner auth показывает spent/reserved/limit/warning_80/blocked по UTC-месяцу. 80% считает расходы вместе с резервациями и добавляет предупреждение к очередному ответу; 100% запрещает новую резервацию. При неизвестном платном исходе учитывается верхняя оценка, повторный платный разбор источника запрещён. Crash оставляет reserved до отдельной сверки счетов; автоматического освобождения нет. Уменьшение лимита действует на запросы; увеличение уже заведённого месяца требует отдельного администрирования, интерфейс повышения не реализован. Уже созданные напоминания доставляются без GPT.

Модель не назначает владельца и не исполняет команды. Только серверная грамматика может немедленно применить очевидную owner-команду. Предложения ИИ требуют версии и подтверждения; даты независимо проверяются по источнику/поясу, подшаги остаются текстовыми draft_steps. Контекст ограничен текущим текстом, датами, до 8 вероятных задач и 8 вопросами, без всего inbox/секретов/owner и Telegram IDs. Без полной уверенности в уникальности выбирается уточнение или явный reply.

Корпус [fixtures/STAGE2_CORPUS.md](fixtures/STAGE2_CORPUS.md): 144 размеченных синтетических примера, 36 held_out. Независимая реальная оценка NLP **Not Run**. Сведения аудита и SDK совместимости — [docs/STAGE2_AUDIT.md](docs/STAGE2_AUDIT.md), доказательства — [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md), фактический план — [EXECPLAN_STAGE2.md](EXECPLAN_STAGE2.md).

Финальный прогон Stage 2: **124 CRM-теста passed, 1 warning, 19.15s** на PostgreSQL 16.10, включая все прежние 69; **133 legacy-теста passed, 1.07s**. Демо ядра, Stage 2, 28-дневная симуляция и оба HTTP smoke в отдельном Compose прошли. Это не live Telegram/GPT, нагрузочный SLO или production-пилот.
## Read-only почта

Реализованы сменный IMAP SSL адаптер, семь суток первичной загрузки, PostgreSQL checkpoint/lease, сверка изменений и только подтверждаемые предложения. Реальный ящик не подключён; оба разрешения выключены. Веб показывает доказательства и состояние сверки. Точные команды синтетического стенда, настройки будущего доступа и ограничения: [docs/MAIL.md](docs/MAIL.md).

## Регулярность и следующий шаг

В карточке доступны календарное повторение и подтверждение целого плана шагов. «Сегодня» предлагает ранний день выполнения и небольшой старт; предпочтительное время для будущих форм сохраняется только после решения владельца. Все данные и версии находятся в PostgreSQL. Семантика, команды запуска и границы: [docs/PLANNING.md](docs/PLANNING.md).
