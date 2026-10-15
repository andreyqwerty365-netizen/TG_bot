# Проверки без домашнего компьютера

Основная ветка: `codex/personal-crm-reliability-web`. Владелец разрешил отдельный `.github/workflows/personal-crm.yml`; остальные изменения остаются внутри модуля CRM. Workflow автоматически запускается после push изменений CRM в эту ветку. Он ничего не развёртывает, не обращается к Amvera и не использует repository secrets. Доступ GITHUB_TOKEN — только contents:read.

Фактическая проверка на 2026-10-15: [run 38707830985](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38707830985), commit ad0c56e, обе jobs success с Python 3.12.15/PostgreSQL 16.15. Пройдены 326 CRM/133 legacy/14 React/18 E2E/load и container generated config/HTTPS/restart/encrypted restore. Полные версии, image IDs и ограничения — в ACCEPTANCE.md. Коммит финальной документации не меняет проверенный runtime/config/workflow.

## Что выполняется на Ubuntu 24.04

Первая job устанавливает Python 3.12, Node 24, PostgreSQL 16 client и зафиксированные зависимости. Новый service PostgreSQL использует явно синтетическую роль/пароль. `scripts/ci_databases.py` создаёт три разные новые БД и отказывается использовать другую роль, удалённый сервер, обычную рабочую БД или перезаписывать output. Ничего из старых локальных баз не требуется.

Далее выполняются CRM tests/миграции/реальное восстановление, legacy tests в отдельном venv, React unit/build, 18 desktop/mobile E2E и нагрузка 10 000 задач/10 клиентов. Browser runner сам запускает API/source только для новой пустой `personal_crm_test_web_ci_*` базы, принудительно отключает внешние адаптеры, назначает свободный loopback port и останавливает только созданные им процессы. Пароль генерируется заново. Очередь доставки для browser лаборатории не запускается.

Вторая job собирает runtime/backup targets Dockerfile.production и использует production Compose с отдельным `crm-check-<random>` project. Все env и bind-папки генерируются заново внутри `.runtime/container-ci-*`; `/etc/personal-crm`, настоящие данные и реальный VPS не используются. Cleanup допускает только собственный project/path; удалённый Docker daemon запрещён.

Для HTTPS используется Caddy internal CA, который доверяется только конкретному HTTP-клиенту проверки. TLS verification не отключается и локальная CA не устанавливается в системный trust store. Production и laboratory Caddy используют общие routes.caddy; боевой Caddyfile сохраняет обычный автоматический публичный TLS.

Конфигурация контейнеров теперь создаётся общей функцией `deployment_setup.render_configuration`: случайные DB credentials/owner/key, Argon2id и image IDs фактической сборки. До замены только lab origin на localhost проходит настоящий offline check всех восьми файлов; после этого тот же комплект используется для HTTPS/restore испытания. Production CLI дополнительно запрещает запись внутри checkout и принимает пароль только через приватный терминал.

Проверяются actual HTTPS/secure cookie/Origin/CSRF, закрытые docs, приложение и очередь после restart, запрет fake delivery в production, реальный pg_dump из backup image и изолированный restore с hold/отозванными сессиями/выключенными напоминаниями. Image IDs и успешный JSON отчёт появляются в summary job. Это local image content IDs, а не опубликованные registry digests.

## Воспроизведение в отдельном облачном окружении

Нужны Python >=3.12, Node 24, настоящая disposable PostgreSQL 16 с ролью crm_test/CREATEDB, PG client 16 и зависимости. Все команды из `personal-crm/`; используй отдельный venv и не подключай рабочую БД.

    python -m pip install -r requirements.lock
    python -m pip install --no-deps --no-build-isolation -e .
    python -m pip check

Явно задать `CRM_CI_ADMIN_URL` на loopback тестового PostgreSQL, пользователь crm_test, database postgres. Команда не читает .env и не выводит DSN:

    python scripts/ci_databases.py --output .runtime/cloud-databases.env

Файл содержит credentials только своего тестового PostgreSQL, имеет mode 0600 на Linux и исключён из Git. Его три переменные нужно загрузить в окружение текущего тестового процесса. На Linux shell:

    while IFS= read -r crm_assignment; do export "$crm_assignment"; done < .runtime/cloud-databases.env
    export CRM_TEST_PG_BIN=/usr/lib/postgresql/16/bin
    python -m pytest -q --tb=short --basetemp=.runtime/pytest-cloud
    cd web
    npm ci
    npm test
    npm run build
    npx playwright install --with-deps chromium --only-shell
    cd ..
    python scripts/browser_checks.py
    python -m personal_crm.load_rehearsal --report .runtime/load-cloud.json

Legacy tests запускаются отдельным окружением из корня: `<legacy-python> -m pytest tests -q`. Не запускать два pytest набора, очищающих одну БД, параллельно. Для повторного полного независимого прогона создать новые БД и новый output filename.

Если доступен локальный Linux Docker Engine и Compose >=2.30:

    python scripts/container_checks.py

Rehearsal самостоятельно собирает images и убирает только свои volumes/контейнеры. При сбое изучить synthetic `.runtime/container-ci-*/commands.log`; приватные env/key/copy файлы и логи целиком в Git не добавлять. Script не поддерживает Docker через SSH/TCP и не должен направляться на боевой Docker host.

## Граница доказательств

GitHub workflow является подготовленной проверкой, а не подтверждением её успеха. Фактические результаты и URL run фиксируются в ACCEPTANCE.md после завершения. GitHub может требовать включить Actions или предоставить интеграции право сохранять workflow; эти состояния нельзя выдавать за выполненные тесты.

Контейнерный restart не является reboot VPS. Internal TLS не проверяет публичные DNS/ACME. Изолированная копия не проверяет настоящий внешний S3, а synthetic Telegram не проверяет реальную доставку. До рабочего запуска отдельно выполнить шаги PILOT_DEPLOYMENT.md, предоставить VPS/DNS/нового бота/S3 и провести приёмку владельца.

Основания: [GitHub service PostgreSQL](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers), [workflow triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [Caddy internal TLS](https://caddyserver.com/docs/caddyfile/directives/tls#internal).
