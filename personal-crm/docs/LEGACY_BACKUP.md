# Ежедневные зашифрованные копии данных старого бота

Дополнение15октября2026: независимо от ежедневного backup установлен еженедельный restore drill CRM и обеих SQLite, воскресенье04:20МСК. Начальный реальный S3 restore прошёл; временный стек удалён, старый receiver не перезапускался. Новый технический бот и бесплатный внешний Cronitor сообщают о сбое/восстановлении. Процедура и границы: [MONITORING.md](MONITORING.md).

Этот пакет независимо копирует `notes.db` и `workouts.sqlite3` в уже оплаченный S3. PostgreSQL CRM имеет собственный backup, ключ и расписание. Новых платных услуг для SQLite не требуется. Данные бота не импортируются в CRM.

## Устройство и границы

`src/personal_crm/legacy_backup.py` снимает каждую базу через SQLite online backup API, включая committed WAL. Снимки двух независимых баз последовательные, общей межбазовой транзакции нет. Нельзя заменять это обычным копированием DB-файла, применять `immutable` к живому источнику или запускать второй Telegram polling для проверки восстановления.

`deploy/legacy_backup_job.py` держит два соединения `mode=ro` и `query_only=ON` на хосте. Они позволяют SQLite создать служебные WAL/SHM, если у простаивающей WAL-базы эти файлы отсутствуют. Исходные страницы БД через эти соединения записывать нельзя. Пока соединения открыты, контейнер получает **read-only bind** исходного каталога. Первоначальный реальный запуск с одним read-only bind отказал на idle notes.db (`SQLITE_CANTOPEN`), поэтому такой wrapper необходим. Writable source mount контейнеру не предоставляется.

Контейнер работает от UID/GID10001, с read-only rootfs, без capabilities и опубликованных портов. Открытые снимки и контрольное восстановление размещаются в `/tmp` tmpfs. На постоянный диск и в S3 пишется AES-256-GCM ciphertext с отдельным случайным ключом 256 бит и отдельным purpose `legacy-sqlite-v1`. Максимум каждой SQLite — 20 MiB, всего ciphertext — 64 MiB; превышение завершает job ошибкой, а не пропуском данных.

После upload программа скачивает объект, сравнивает ciphertext, расшифровывает и действительно восстанавливает обе базы в tmpfs. Проверяются `integrity_check`, schema fingerprint, количество и hash всех строк каждой таблицы, включая FTS-таблицы. Затем публикуется зашифрованный `latest.botb` и проверяется его readback. Только после этого можно удалять собственные аутентичные архивы старше 30 дней. Чужие/повреждённые объекты не удаляются. Сбой до проверки не удаляет предыдущие копии. Уникальные имена и lock защищают от параллельных запусков; аварийно оставшийся lock требует проверки оператором.

Отдельный private bucket использует имеющиеся storage credentials. API-проверка ACL исключила public grants; отдельные IAM-права на prefix не доказаны. Шифрование выполняется до отправки. Ключ не входит в архив и не совпадает с CRM key. Token, env, логи и runtime бота в архив данных не входят; приватную конфигурацию и проверенный runtime нужно хранить отдельно. Без ключа восстановление невозможно.

## Установка оператором

Все команды далее выполняются на VPS от администратора из `/opt/personal-crm/repository/personal-crm`. Они относятся только к отдельному backup project. Не выполнять `up`/`restart` существующего bot project. Реальные значения и immutable image IDs берутся из приватного журнала оператора.

После проверки ID существующего локального CRM backup image собрать новый job без сетевых RUN:

    docker image inspect personal-crm-backup:operator-pinned --format '{{.Id}}'
    docker build --pull=false --network=none --build-arg LEGACY_BACKUP_BASE=personal-crm-backup:operator-pinned -f deploy/Dockerfile.legacy-backup -t legacy-data-backup:operator-pinned .
    docker image inspect legacy-data-backup:operator-pinned --format '{{.Id}}'

В `FROM` нужен локальный tag, ID отдельно проверяется и записывается. BuildKit трактует голый `sha256:...` как repository name. `RUN chmod` предоставляет UID10001 чтение только кода скопированного пакета; приватные данные в build context не помещать.

В `/etc/legacy-reminder-bot/config` (0700 root) подготовить `backup.env` и `backup-deploy.env` (0600 root) по двум примерам `deploy/examples/legacy-backup*.example`. Endpoint только HTTPS; отдельные bucket/prefix; `LEGACY_BACKUP_CONFIRMED=true` после подтверждения назначения. В deploy env указать точный inspected image ID, существующий каталог данных и отдельный encrypted-backups. Ключ `recovery-key.txt` содержит base64url 32 случайных байт, владелец10001, mode0400; root-private родитель защищает его на хосте. На контейнер ключ монтируется отдельным read-only файлом. Каталог encrypted-backups создать 0700 UID10001. Не выводить `env`, `docker inspect` целиком или `compose config` с секретами.

    docker compose --env-file /etc/legacy-reminder-bot/config/backup-deploy.env -f deploy/compose.legacy-backup.yaml config --quiet
    python3 deploy/legacy_backup_job.py

Успех: JSON `status=verified_remote` и две базы. `last-success.json` в encrypted-backups содержит только проверочный отчёт, не тексты строк. Если процесс завершён аварийно, сначала проверить отсутствие другого backup job; только затем убрать `.job.lock`. Существующий ciphertext предыдущих копий не удалять.

Установить ежедневный timer:

    install -m 644 deploy/systemd/legacy-data-backup.service /etc/systemd/system/
    install -m 644 deploy/systemd/legacy-data-backup.timer /etc/systemd/system/
    systemd-analyze verify /etc/systemd/system/legacy-data-backup.service /etc/systemd/system/legacy-data-backup.timer
    systemctl daemon-reload
    systemctl enable --now legacy-data-backup.timer
    systemctl start legacy-data-backup.service
    systemctl show legacy-data-backup.service -p Result -p ExecMainStatus
    systemctl list-timers legacy-data-backup.timer --no-pager

Расписание **03:20 Europe/Moscow**, точность 1 минута, независимо от timezone сервера. `Persistent=true` выполняет пропущенный календарный запуск после включения сервера. Service ограничен 10 минутами, wrapper — 9 минутами. После timeout проверить контейнер/lock перед повтором. Обычный ручной повтор безопасен, создаёт новую копию. Таймер включён на boot; reboot именно этого нового timer пока не испытывался. Журнал/failed unit доступны через systemd, независимые уведомления оператору и регулярная restore-репетиция не настроены.

## Восстановление без запуска бота

Ключ сохранить вне VPS в менеджере паролей; в текущем размещении отдельная копия передана в ранее согласованный приватный Windows-каталог. Не хранить единственную копию ключа во временной папке. Для аварийного восстановления требуются также S3 credentials и этот исходник/проверенный image. Ниже восстанавливаются только данные в **новый** каталог, процесс Telegram не запускается:

    install -d -m 700 -o 10001 -g 10001 /srv/legacy-reminder-bot/restore-rehearsals
    docker compose --env-file /etc/legacy-reminder-bot/config/backup-deploy.env -f deploy/compose.legacy-backup.yaml run --rm -T --interactive=false --volume /srv/legacy-reminder-bot/restore-rehearsals:/restore backup download-restore --target /restore/unique-new-name

Без `--object` используется проверяемый encrypted latest. Конкретную старую точку можно выбрать через `--object legacy-bot/archives/<имя.botb>`. При существующем каталоге, symlink, неверном ключе, повреждении шифротекста, неполной паре или неверных hash команда отказывает. Обход путей невозможен: принимаются только два фиксированных имени файлов. `RESTORE_REPORT.json` должен показать `restored_verified`; fingerprint следует сравнить с исходным отчётом upload. Не заменять `/data` живого бота результатом репетиции. Для настоящего переключения потребуются остановка единственного receiver, проверенный rollback и отдельная процедура.

## Проверки

Из personal-crm: `.venv/Scripts/python.exe -m pytest tests/test_legacy_backup.py -q`. Набор покрывает committed WAL при открытом writer, обе базы, ошибочный ключ/изменённый ciphertext, поддельный manifest/hash/path, неполный источник, запрет существующего/symlink target, повреждённый SQLite, S3 readback/ошибку upload, retention scope, concurrent lock, encrypted latest download и закрытые readonly соединения wrapper. Синтетические тесты не обращаются в Telegram/S3.

Фактическая проверка 2026-10-15: реальный отдельный S3 bucket имеет private ACL; первая копия получила `verified_remote`, затем отдельный `download-restore` восстановил обе базы из S3, fingerprint обеих баз совпал с manifest исходной копии, отдельный `integrity_check=ok` подтверждён. Рабочий бот оставался running/healthy/restarts0, CRM ready200. Ключ вынесен с VPS. Timer enabled/active, следующий запуск 2026-10-16 03:20 MSK. Фактический service запуск 15:01:16–15:01:23 MSK завершился Result=success/ExecMainStatus=0 и новой verified_remote копией двух баз. Anonymous HEAD реального S3 object вернул 403. Backup image ID и приватные object names записаны в операторском журнале, не являются публичными параметрами восстановления.

Финальный regression: полный Windows backend suite с PYTHONUTF8=1, -X utf8, настоящими disposable PostgreSQL/pg_dump/pg_restore — **340 passed, 2 skipped**, 105.59s. Пропуски: POSIX permissions и symlink privileges Windows. Новый набор на Linux от UID10001, network none, read-only rootfs — **16 passed**, 2.62s. До UTF8 режима существующий corpus test отказал на CP1251, после изменения только окружения полный suite прошёл. React и архивные 151 тест бота не повторялись: их исходники/зависимости/runtime этим этапом не менялись.
