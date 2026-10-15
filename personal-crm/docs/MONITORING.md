# Уведомления о сбоях и регулярное восстановление

Этот пакет работает отдельно от CRM и старого бота. Технические уведомления отправляются только новому боту, выбранному владельцем; receiver/polling ему не нужен. Нет новых записей задач, запуска восстановленного приложения или перезапуска рабочих сервисов. Секреты и фактические отчёты остаются вне Git. Текущая приёмка фиксируется в EXECPLAN_MONITORING.md; установка файлов сама по себе не доказывает настройку внешнего наблюдателя или доставку.

## Что проверяется

`crm-ops-monitor.timer` запускает host-only `deploy/ops_monitor.py` каждые две минуты. Проверяются доверенный публичный HTTPS `/ready`, running/health CRM/БД/Caddy/source/backup/старого бота, source heartbeat не старше180секунд, возраст успешных CRM/legacy копий не больше26часов, успешность последнего restore и возраст не больше8дней, запас диска не менее3GiB и10%, состояние backup timer/service. Проверки не читают тексты задач или сообщений. Хранятся только времена, безопасные статусы и счётчики переходов.

Два последовательных сбоя отправляют одно сообщение с фиксированными названиями проверок. Длительный сбой не повторяет сообщения. Две успешных проверки после доставленного alert отправляют восстановление. При ошибке Telegram результат не помечается доставленным; следующий запуск повторяет попытку. Сетевой неопределённый исход может дать дубль — exactly-once Telegram не обещается. Несколько изменений группируются в одно сообщение. Владелец должен сначала нажать Start в новом боте; chat ID сверяется с существующим единственным владельцем, не выбирается первый посторонний посетитель. Telegram использует проверенный IPv6 маршрут VPS без отключения TLS.

## Проверка настоящих копий

`crm-restore-drill.timer`: каждое воскресенье04:20 Europe/Moscow, Persistent=true. `restore_drill_job.py` держит lock и создаёт уникальный Compose project `crm-restore-check-<random>`. Он не подключён к production Docker networks и не публикует портов. PostgreSQL16.15 хранит восстановленные данные в tmpfs, с отдельной ролью/drill и случайным одноразовым паролем. Verifier работаетUID10001, read-only rootfs, без capabilities, с ограничениями CPU/RAM; открытые SQLite и архивы только в tmpfs. Исходный каталог живого бота не монтируется. Из production DSN извлекается только host/port/database для S3 scope, имя пользователя и пароль БД не передаются.

Verifier заново скачивает latest CRM archive и актуальный erasure ledger из S3, проверяет шифрование/manifest/hash/возраст до30часов и реально запускает pg_restore в пустую `personal_crm_restore_drill` на фиксированном host `restore-db`. Восстановление транзакционно сверяет counts и применяет recovery hold, revocation sessions, отмену очередей и остановку интеграций; отдельная проверка подтверждает fences. Другой host/роль/имя БД запрещены до download. Отдельно скачивается latest legacy archive, восстанавливаются обе SQLite и проверяются integrity/schema/row fingerprints. Семейства независимы: отказ одного не скрывает результат другого. Новые локальные снимки живых данных или S3 upload/retention не выполняются.

Затем wrapper удаляет только свой точный Compose project и временный каталог, включая ошибку и timeout. Никакие production volumes не удаляются. Safe reports `restore-last-run.json` и `restore-last-success.json` содержат только status/времена/компоненты; не содержат counts таблиц, owners, исходные строки, имена S3 objects или provider diagnostics. Ошибка setup/cleanup обновляет last-run=failed, прежний success не маскирует её. Сервис ограничен14минутами; перед повтором после жёсткого аварийного убийства нужно проверить оставшийся точный project. При смерти Docker daemon гарантия немедленной уборки невозможна, монитор должен сообщить отказ.

## Установка

Сначала проверить реальный base backup image с PostgreSQL16 clients и сохранить егоID приватно. Использовать отдельный tag локального образа; рабочие CRM images и legacy runtime не менять.

    docker build --pull=false --network=none --build-arg OPS_BASE=personal-crm-backup:operator-pinned -f deploy/Dockerfile.ops -t personal-crm-ops:operator-pinned .
    docker image inspect personal-crm-ops:operator-pinned --format '{{.Id}}'

Подготовить `/etc/personal-crm/monitoring` mode0700 root, `monitor.json` и `restore-deploy.env` mode0600 по examples. Каталог ops-reports mode0700 UID10001, monitor-state mode0700 root. В restore-deploy указать inspected immutable OPS_IMAGE. Фактический путь legacy last-success взять из действующего backup-deploy.env, не предполагать пример. Сначала выполнить ручной restore, затем проверить Telegram тест. Не включать monitor с отсутствующим restore report и не выдавать пустые placeholders за настроенную интеграцию.

    python3 deploy/restore_drill_job.py
    python3 deploy/ops_monitor.py --test-message
    python3 deploy/ops_monitor.py
    install -m644 deploy/systemd/crm-restore-drill.service deploy/systemd/crm-restore-drill.timer deploy/systemd/crm-ops-monitor.service deploy/systemd/crm-ops-monitor.timer /etc/systemd/system/
    systemd-analyze verify /etc/systemd/system/crm-restore-drill.service /etc/systemd/system/crm-restore-drill.timer /etc/systemd/system/crm-ops-monitor.service /etc/systemd/system/crm-ops-monitor.timer
    systemctl daemon-reload
    systemctl enable --now crm-restore-drill.timer crm-ops-monitor.timer

Проверять `systemctl show <service> -p Result -p ExecMainStatus`, enabled/active timers, safe reports и реальную доставку. Для controlled incident использовать отдельное тестовое состояние monitor, не останавливать PostgreSQL/CRM/бота и не подделывать основной last-success. Для отката отключить только эти два новых timer, не затрагивая legacy-data-backup.timer.

## Внешний контроль полного отключения

Процесс на VPS не может отправить уведомление, когда весь сервер или сеть отключены. Для этого подготовлен бесплатный [Healthchecks.io Hobbyist](https://healthchecks.io/pricing/): на15октября2026 он включает20 checks без карты. Нужен аккаунт владельца, отдельная проверка heartbeat с period120секунд/grace180секунд и webhook integration нового технического бота для down/up. Приватный pingURL вида `https://hc-ping.com/<uuid>` задаётся в monitor.json. Каждая выполненная проверка посылает пустой ping, устойчивый сбой — `/fail`; пропуск ping обнаруживается независимо от VPS. URL и bot token не публикуются. Telegram webhook action получает только фиксированный текст состояния, без логов/задач/баз. До создания account/check/webhook и controlled fail/recovery теста внешняя часть считается неподключённой. Следующий календарный запуск/boot новых timer оцениваются отдельно от ручного service запуска.
