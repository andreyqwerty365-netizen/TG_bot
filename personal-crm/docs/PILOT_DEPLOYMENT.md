# Первый запуск на общем VPS

Подготовлен код и пакет размещения. Linux images, Caddy HTTPS с локальной CA, сессии/очередь после restart и encrypted isolated restore проверены на Ubuntu в [успешном CI 38704316507](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38704316507), source commit 91ba0df. Production Python 3.12.15/PostgreSQL 16.15. Настоящие VPS, публичные DNS/ACME, reboot VPS, Telegram, внешнее S3 и перенос Amvera **не выполнены**. Использование начинается после оставшихся шагов ниже; CI не является развёртыванием CRM.

## Данные от владельца

Нужны выбранный домен, VPS Ubuntu 24.04 с SSH, отдельный новый CRM-бот, подтверждённые Telegram user/chat ID, внешний S3 bucket и credentials. Реальные секреты вводятся в `/etc/personal-crm`, не в GitHub/issue/этот документ. У двух старых ботов нужно отдельно выяснить repository/ref, команду запуска и persistent paths. Пока этого нет, Amvera продолжает работать.

## Сборка и конфигурация

На Linux установить Docker Engine и Compose **>=2.30**, создать checkout точного проверенного commit. Production использует только `compose.production.yaml`; development файл с ним не объединять. Сборка получает Linux зависимости из lockfile и собирает React из package-lock; Windows wheels не используются.

    docker build -f Dockerfile.production --target runtime -t personal-crm:pilot-COMMIT .
    docker build -f Dockerfile.production --target backup -t personal-crm-backup:pilot-COMMIT .
    docker image inspect personal-crm:pilot-COMMIT --format '{{.Id}}'
    docker image inspect personal-crm-backup:pilot-COMMIT --format '{{.Id}}'

Сохранить два полученных `sha256:...` в CRM_IMAGE/CRM_BACKUP_IMAGE. Проверить `pg_dump --version` у backup image: major 16, клиент не старше сервера. Перед реальным запуском обновления базовых Python/Node/PostgreSQL/Caddy images проверяются на Linux, затем сохраняются их точные digests и результаты в приватном журнале. Имена тегов в шаблоне не являются проверенным digest.

Создать `/etc/personal-crm` root:root mode 0700. Скопировать только пустые примеры `deploy/examples/*.env.example` в одноимённые `*.env`, chmod 0600. Дополнительно создать `db-password` mode 0600 с новым паролем PostgreSQL. В database.env указать URL `postgresql+psycopg://crm:<URL-encoded-password>@db:5432/personal_crm`; пароль должен соответствовать db-password. Не менять пароль уже созданного volume простым редактированием env: это не обновляет роль PostgreSQL.

В identity.env задать новый owner и Europe/Moscow; в deploy.env — согласованный CRM_HOST, ACME_EMAIL и два image ID. В web.env — `CRM_WEB_ORIGIN=https://<CRM_HOST>` без пути и завершающего `/`. Хэш нового пароля получить интерактивно:

    python -m personal_crm.pilot_setup password-hash

Пароль от 12 символов вводится без отображения, два раза; аргумент с паролем не поддерживается. Команда выводит только Argon2id hash. Его целиком, **без кавычек**, внести в web.env. `env_file: format: raw` сохраняет символы `$` хэша. Синтетические значения и пароль `synthetic-web-local` в production не переносить. CRM_OWNER_TOKEN можно оставить пустым: обычный вход теперь через пароль.

Флаги AI/mail жёстко выключены в production шаблоне. Ingress/delivery/backup первоначально выключены; optional процессы запускаются профилями после настройки. У API/source нет S3 ключа, у backup нет пароля веба/токена Telegram. PG/API порты на хост не публикуются; Caddy занимает 80/443. Сеть proxy `172.30.71.0/28` не должна конфликтовать с существующими сетями. Uvicorn доверяет forwarded headers только фиксированному Caddy `172.30.71.2`; wildcard доверия отсутствует. При смене подсети одновременно изменить Caddy IP и команду Uvicorn, пересобрать image.

Бюджет контейнеров: PG 768 MiB, API 512, source 256, delivery 256, backup 384, Caddy 128; это лимиты, не замер потребления. RAM остальных ботов и ОС нужно измерить отдельно. Контейнеры имеют restart policy и ограниченные журналы; unhealthy сам по себе не означает автоматический restart. Docker daemon должен запускаться после reboot.

## Первый запуск и внешний backup

    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml config --quiet
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml up -d db
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml run --rm migrate
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml run --rm --no-deps api python -m personal_crm.pilot_setup initialize-owner
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml up -d api source caddy

Init owner повторяемый: создаёт сводку 09:00 и одну инициативу/сутки только у нового профиля; последующие пользовательские настройки не перезаписывает. DNS A должен указывать на VPS. Проверить HTTPS, `/health`, `/ready`, вход, reload, logout, телефон. `/ready` проверяет фактическую схему, hold и свежесть включённых обработчиков, а не сообщает фиктивную готовность.

Создать `/srv/personal-crm/backups` и `/srv/personal-crm/ledger` с владельцем UID/GID 10002 и mode 0700. Создать новый ключ через `personal_crm.maintenance keygen`, сохранить **независимую приватную копию вне VPS и bucket**; в backup.env задать ключ, HTTPS endpoint/bucket/credentials. Bucket принадлежит владельцу, права ключа ограничены отдельным CRM prefix. Включить обе CRM_BACKUP_ENABLED/CRM_S3_ENABLED и CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED только после проверки внешнего назначения. В web.env также включить backup/S3 флаги, чтобы статус и readiness учитывали этот процесс.

    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml --profile backup run --rm --no-deps backup python -m personal_crm.maintenance init-ledger
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml --profile backup run --rm --no-deps backup python -m personal_crm.remote_backup --once
    docker compose --env-file /etc/personal-crm/deploy.env -f compose.production.yaml --profile backup up -d backup api

Первый результат должен быть `verified_remote`. Повтор раньше 24 часов — `not_due`; возраст последней копии сохраняется между рестартами. Каждая новая копия шифруется AES-256-GCM до upload, читается обратно и проверяется. Retention 30 дней только того же scope после новой подтверждённой remote копии; upload failure не удаляет прежнюю. Размер архива ограничен 64 MiB: при превышении worker сообщает ошибку, требуется пересмотр вместимости, лимит не отключать молча.

Erasure ledger публикуется отдельно при изменении; локальное уменьшение уже удалённых owner запрещено. После `erase-owner` отдельно скопировать свежий encrypted ledger и ключ в независимое место и запустить `remote_backup --once`, проверить marker; не считать локальное удаление свидетельством обновления внешних копий. Если остался `.lock` после crash, сначала остановить backup/maintenance и убедиться, что операции больше нет; только потом убрать именно этот lock. Автоматического снятия lock нет.

## Восстановление и наблюдение

До личного ввода скачать копию из S3 в **пустую** директорию через `personal_crm.remote_backup --download <directory>` на отдельном разрешённом стенде. Настроить тот же key и scope исходной БД; исходная БД для скачивания не подключается. Затем использовать скачанный актуальный `erasures.crme`, новый пустой PostgreSQL target `personal_crm_restore_<name>` и existing `personal_crm.maintenance restore <archive>`. Target должен быть действительно отдельным. Сверить manifest/counts, сессии отозваны, profiles on hold, старые paid/unknown outcomes и reminders не отправляются. `release-hold` — только после приватной сверки; интеграции сами не включаются. Production restore командой не поддерживается: перенос результата в рабочую БД требует отдельного согласованного переключения.

Повторять изолированное восстановление ежемесячно и перед рискованными миграциями. Зафиксировать дату, archive digest, target, counts и время в приватном журнале. Эти регулярные проверки ещё не запланированы и не выполнены на настоящем S3.

На независимом внешнем мониторе настроить HTTPS `/ready` каждую минуту, уведомление владельцу после двух ошибок; monitor вне VPS нужен для обнаружения его полного отключения. Монитор и уведомления ещё не подключены. Локальные worker heartbeats 30/5/60 секунд, просрочка 90 секунд; предупреждение по копии >26 часов. В «Настройки → Работа CRM» видны очередь, ошибки и неопределённые исходы. Unknown не повторять без фактической проверки доставки.

На VPS измерить `docker stats`, диск и reboot. Тревоги: RAM >85% 10 минут, диск >80%, backup >26 часов, stale/error worker, failed/unknown delivery. Не увеличивать тариф автоматически. Полный набор CRM/legacy/unit/E2E + synthetic load rehearsal повторить на Linux; его локальный Windows результат не доказывает размер VPS. После reboot проверить HTTPS, сохранённый вход, фактическое сообщение и копию.

## Отдельный Telegram и дальнейший перенос

Выбранный новый бот проверить через getMe в приватной процедуре; не использовать токен Amvera. В ingress.env задать webhook secret, bot ID, allowlist; delivery.env — его token и единственный outbound chat. CRM_TELEGRAM_SEND_ENABLED должен совпадать в web.env/delivery.env. После backup rehearsal включить webhook и профиль telegram, зарегистрировать HTTPS `/telegram/webhook` с `secret_token` через приватный операторский инструмент, проверить сообщение → сохранение → ответ, точное напоминание, отмену, сводку. Код не регистрирует webhook и не отправляет getMe автоматически.

Пять личных учебных дел, один проект и одна серия — приёмка владельца; затем семь дней ежедневного использования. Короткая инструкция — `USER_GUIDE.md`.

Amvera переносить отдельно по `EXECPLAN_PILOT.md`: один бот, согласованное окно, последняя согласованная SQLite копия, hash/counts, единственный polling receiver, проверка тренировок/расписания/отката. Второе приложение ещё не идентифицировано. Не выключать оба и не закрывать тариф до проверки. Production legacy import пока запрещён existing guard; перед этим нужен подтверждённый preview/hash, backup текущей CRM, отдельная защищённая команда и испытание rollback. Разрешён только existing изолированный rehearsal, без запуска старых уведомлений.

## Обновление

Проверки без домашнего компьютера доступны отдельным workflow и переносимыми скриптами: [CLOUD_CHECKS.md](CLOUD_CHECKS.md). Динамический pool proxy сети ограничен 172.30.71.8/29 внутри subnet 172.30.71.0/28: Caddy 172.30.71.2 не должен автоматически назначаться API. При смене subnet нужно согласованно менять static IP, dynamic pool и доверенный адрес Uvicorn.

Сохранить verified remote backup и два текущих image digests. Проверить новую версию на отдельной БД, совместимость схемы и restore. Остановить доставку на время согласованного обновления, выполнить миграцию однократно, сменить image IDs и запустить процессы; проверить readiness и данные. Откат image допустим только при подтверждённой совместимости схемы. При её отсутствии — согласованное восстановление/переключение; не downgrade рабочую БД автоматически. Новые записи после переключения учитывать при откате. GitHub не связан с автоматическим непроверенным production deploy.

Основания конфигурации: [Compose services](https://docs.docker.com/reference/compose-file/services/), [raw env_file](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/), [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [PostgreSQL client repository](https://www.postgresql.org/download/linux/debian/).
