# Резервирование и пробный перенос

Команды выполняются из `personal-crm/` на хосте с Python 3.12 и PostgreSQL 16 client tools (`pg_dump`, `pg_restore`, `psql`). Docker image этих tools не содержит. Production/реальные каналы не запускались. Поля `.env.example` для ключа и путей пусты; их нужно настроить в серверном окружении. Личные копии не хранить в рабочем Git-каталоге.

## Копия и ежедневный цикл

`python -m personal_crm.maintenance keygen` генерирует случайный 256-bit URL-safe base64 ключ. Сохранить его отдельно в менеджере секретов; `CRM_BACKUP_KEY` содержит этот ключ, а не произвольный пароль. Утрата ключа делает восстановление невозможным. Он не включается в БД, архив, Git или аргументы дочерних процессов.

Настроить `CRM_DATABASE_URL`, `CRM_PG_BIN` (каталог PG binaries), `CRM_BACKUP_DIRECTORY` (существующий каталог назначения), `CRM_ERASURE_LEDGER` (отдельный журнал удалений). Один раз создать **новый** журнал; существующий не перезаписывается:

    python -m personal_crm.maintenance init-ledger
    python -m personal_crm.maintenance backup
    python -m personal_crm.maintenance inspect <archive.crmb>

`backed_up` сообщает имя архива и количества строк без личных текстов/идентификаторов. Формат v1: AES-256-GCM, случайный nonce 96 bit, разные authenticated purpose для backup/ledger/export, зашифрованные manifest и pg_dump с SHA-256. Counts и custom dump читают один PostgreSQL MVCC snapshot. Поддерживается схема `ca294b816edf`; несовместимая ревизия отвергается. Plaintext временные файлы не создаются. Файл fsync/atomic публикуется, затем повторно читается/проверяется. Только после этого удаляются проверяемые копии той же базы старше 30 дней. Чужие, повреждённые, symlink и зашифрованные другим ключом файлы автоматически не удаляются. При ротации ключа сроки старых копий контролируются отдельно.

Лимит зашифрованного архива 64 MiB, timeout PostgreSQL subprocess 120s. Dump/SQL buffers находятся в памяти; это не потоковый инструмент для больших баз. Для них нужен отдельный формат и испытания.

`CRM_BACKUP_ENABLED=false` по умолчанию: следующая команда возвращает `disabled`, не подключаясь к БД и не создавая файлов:

    python -m personal_crm.maintenance backup-loop --once

Для ежедневного цикла нужны ключ/журнал/каталог на **проверенном внешнем носителе или удалённом mount**, `CRM_BACKUP_ENABLED=true` и `CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED=true`:

    python -m personal_crm.maintenance backup-loop

Один supervised процесс проверяет срок раз в минуту; новая копия создаётся через 24 часа после последней аутентифицированной копии этой базы. Рестарт не сбрасывает срок. Ошибка возвращает безопасный код (и ненулевой exit при `--once`); процесс повторяет через минуту. Контролировать ошибки и возраст последней копии. Штатный RPO — до 24h, при остановленном/неисправном процессе он не гарантируется.

Флаг подтверждения не доказывает физическое расположение mount. **Внешний носитель, supervisor и оповещение оператора здесь не настроены/не испытаны. D17 частично проверен.** Единственные ключ и журнал нельзя хранить только на уничтожаемом сервере. Локальные синтетические тесты не являются off-server backup.

## Восстановление

Создать пустую отдельную БД `personal_crm_restore_<name>` / `personal_crm_test_restore_<name>`. Другие имена и существующие relations отвергаются. Сервисы к ней не подключать. `CRM_RESTORE_DATABASE_URL` задаёт её отдельно от исходной. Предоставить **последний внешний** `CRM_ERASURE_LEDGER` и ключ; отсутствие/повреждение журнала блокирует процедуру.

    python -m personal_crm.maintenance restore <archive.crmb>

Schema/data, проверка counts всех таблиц, повторное применение удалений и карантин commit одной транзакцией psql. Ошибка оставляет пустую базу. Пустая public пересоздаётся без CASCADE. Исходная база не меняется. PostgreSQL credentials передаются через окружение; stderr с потенциальным личным SQL не выводится.

`restored_on_hold` означает сохранность дел/дат/источников/истории и блокировку профилей `recovery_hold`. HTTP возвращает `503 recovery_hold`, команды/Telegram ingest/разбор/mail/claim и доставка блокируются. Pending/leased jobs отменены с `restore_hold`; pending delivery attempts и reserved AI запросы становятся unknown. Уже unknown не повторяются. Незавершённые источники сохраняются с `restore_review_required`, без повторного платного разбора. Reminders неактивны, серии остановлены, ИИ приостановлен, почта отключена. Состояния самих дел и сроки сохраняются.

Сверить export/counts, владельца и отказ чужому credential, несколько текстов/сроков/reminder moments, jobs/attempts/резервы. Затем при явно заданном `CRM_OWNER_ID`:

    python -m personal_crm.maintenance release-hold

Команда разрешена только для isolated restore и оставляет старую очередь/ИИ/почту/серии выключенными. Будущие уведомления назначаются заново явными действиями владельца. Незавершённые источники просмотреть/экспортировать, затем явно ввести повторно при необходимости. Автоматического replay нет. Перенос в production и повторное включение внешних каналов требуют отдельного разрешённого runbook; здесь не выполнялись.

## Удаления и экспорт

Поддержано **удаление целого профиля**, выборочная очистка задачи/письма пока отсутствует. Остановить все CRM процессы и отозвать серверный credential/внешние разрешения удаляемого владельца. При заданном `CRM_OWNER_ID` maintenance-команда `erase-owner --confirm-owner <тот_же_owner>` сначала атомарно/fsync записывает SHA-256 идентичности в отдельный encrypted журнал, затем транзакционно удаляет данные с учётом FK. В сессии она запускалась только на synthetic fixtures. Повтор после сбоя БД завершает удаление; старый backup при restore снова очищается по актуальному журналу. Чужие профили сохраняются; зашифрованные старые копии истекают по 30-дневной политике.

Restore/erase/release используют эксклюзивный `.lock` рядом с журналом, конкурирующая операция получает `ledger_busy`. После падения lock остаётся: убрать его вручную только после проверки завершения maintenance и сохранности журнала. Не заменять утраченный журнал пустым. Защита внешнего журнала от отката старой версией и хранение его независимых копий — обязанность оператора. Оставленная серверная конфигурация может заново зарегистрировать удалённого владельца; поэтому отзыв разрешений обязателен.

Веб: «Настройки → Экспорт → Скачать мои данные». `GET /workspace/export` требует owner Bearer, отдаёт attachment/no-store JSON: профиль, проекты, задачи/заметки/сроки, серии/шаги, источники в пределах хранения, предложения, история и reminders. Чужие данные, серверные ключи и delivery leases не включены. JSON скачивается **без шифрования**, что указано в интерфейсе; браузер не кладёт его в localStorage. Для encrypted export:

    python -m personal_crm.maintenance export <destination.crmx>

Offline-чтение в доверенном окружении: `personal_crm.recovery.unseal(bytes, key, "export")`. Пользовательский экспорт не заменяет backup очереди.

## Копия старого бота

Импортер опирается на прочитанные `bot/db.py` и `bot/utils/date_utils.py`, но не импортирует/не запускает старого бота. Нужна отдельно разрешённая **standalone SQLite backup API копия** (`backup_to`), а не файл открытой WAL-базы. `-wal/-shm/-journal` отвергаются. Чтение `mode=ro&immutable=1`, query_only/trusted_schema=OFF, hash до/после, максимум 64 MiB/10 000 выбранных строк, validation до PostgreSQL записи.

    python -m personal_crm.maintenance legacy-preview <copy.sqlite> --chat <selected_chat> --timezone Europe/Moscow

Preview не пишет в БД; показывает hash, counts notes/reminders и повторы/просроченные active reminders. Chat и IANA timezone выбираются явно; прежний фиксированный offset не превращается в сезонный пояс. Naive timestamp — UTC согласно фактическому legacy-контракту.

Создать/мигрировать отдельную rehearsal PostgreSQL `personal_crm_test_import_<name>`, зарегистрировать нужного владельца с выбранным поясом. `CRM_DATABASE_URL`/`CRM_OWNER_ID` задают эту БД/владельца. Стабильный namespace обозначает одну линию исходной базы, SHA-256 берётся из preview:

    python -m personal_crm.maintenance legacy-import <copy.sqlite> --chat <selected_chat> --timezone Europe/Moscow --namespace legacy-v1 --expected-sha256 <preview_sha256>

Разрешены только `personal_crm_test*` / `personal_crm_restore_*`. Notes остаются notes. Archived без done → cancelled; done_at → done. Remind_at сохраняется неактивным reminder и исходным evidence, не становится дедлайном/планом. Repeat_rule остаётся evidence; новая серия не включается автоматически. Веб-карточка показывает прежнее время/правило для проверки. Старые offset/dayplan сохранены в metadata, без запуска сводок. Job/sender/ИИ/IMAP не создаются.

Повтор owner/namespace/table/id пропускает идентичные строки. Изменённая строка даёт `legacy_record_conflict` и rollback всего batch; автоматического слияния нет. Изменившаяся после preview копия требует нового просмотра. Чужие chats не выбираются, routine/training/shift таблицы не импортируются и не меняются. Реальная копия старой базы пользователем пока не предоставлена; проверены только synthetic fixtures.

## Проверки

`CRM_TEST_DATABASE_URL` должен указывать на disposable `personal_crm_test*`: fixture удаляет её схему. `CRM_TEST_PG_BIN` — PG16 binaries; без tools dump/restore тесты явно skip. Test role нужен CREATE DATABASE для случайных `personal_crm_test_restore_<uuid>`, удаляемых в finally.

    python -m pytest tests/test_recovery.py tests/test_legacy_import.py -q --basetemp=.runtime/test-recovery
    python -m pytest -q --basetemp=.runtime/test-full
    cd web
    npm test
    npm run build
    npm run test:e2e

Проверяются настоящий pg_dump/restore/psql, concurrent snapshot, count rollback, неизвестные доставки/paid requests, ledger replay/lock, чужой target/key/owner, 30-дневное хранение/daily due, readonly/idempotent import и protected HTTP export. Ключи/данные только синтетические. Механизмы описаны в [AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM), [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html); результат приложения подтверждается тестами.
