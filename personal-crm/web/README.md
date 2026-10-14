# Веб-интерфейс Personal CRM

React + TypeScript поверх существующего FastAPI/PostgreSQL. Работают Сегодня, Все дела с серверным поиском/фильтрами/страницами, Входящие с подтверждением и уточнениями, Проекты и Настройки. Данные задач не сохраняются в localStorage или отдельной клиентской базе.

## Запуск

Нужен Node.js 24. Из `personal-crm/web`:

    npm ci
    npm test
    npm run build

Из `personal-crm` задать локальные `CRM_DATABASE_URL`, `CRM_OWNER_ID`, `CRM_TIMEZONE`, `CRM_WEB_PASSWORD_HASH`, `CRM_WEB_ORIGIN=http://127.0.0.1:8001`, `CRM_WEB_INSECURE_LOCALHOST=true`; hash получить интерактивной `python -m personal_crm.pilot_setup password-hash`. Применить `python -m alembic upgrade head` и запустить:

    .venv\Scripts\python.exe -m uvicorn personal_crm.api:create_app --factory --host 127.0.0.1 --port 8001

Открыть `http://127.0.0.1:8001/app/`. Ввести пароль, для которого создан hash. Вход сохраняется серверной HttpOnly cookie на 30 дней; logout отзывает сессию. Пароль/credential не сохраняются в localStorage/sessionStorage. CRM_OWNER_TOKEN оставлен для явных CLI Bearer запросов и не нужен для обычного веб-входа. Модель/почта/Telegram выключены. Для непрерывного разбора отдельно запустить `personal_crm.source_worker`; production доставка не имитируется при выключенном Telegram.

При разработке `npm run dev` открывает `http://127.0.0.1:5173/app/` и проксирует запросы, включая /auth, к backend на порту 8001. Для этого режима у backend явно задать `CRM_WEB_ORIGIN=http://127.0.0.1:5173`; Host/Origin сохраняются proxy. Сначала запустить backend. Для другого адреса изменить локальную настройку proxy в vite.config.ts. Постоянные данные остаются в PostgreSQL.

Перед Docker build также выполнить `npm ci` и `npm run build`: Dockerfile копирует готовый `web/dist` в образ, Python wheels готовятся прежним `scripts/prepare_wheels.py`. Docker в этой Windows-сессии отсутствует, сборка контейнера не проверялась.

Для VPS есть самостоятельный Dockerfile.production с frontend build и Linux-зависимостями: [первый запуск](../docs/PILOT_DEPLOYMENT.md), [короткая инструкция](../docs/USER_GUIDE.md).

## Проверки

`npm test` — unit-проверки React с имитацией HTTP; они проверяют интерфейс, но не БД. `npm run build` — TypeScript и сборка. Сквозные `npm run test:e2e` используют настоящий локальный backend и PostgreSQL; не подменяют API ответами из fixtures. Нужна отдельная синтетическая БД `personal_crm_test_web`, владелец/credential из собственной тестовой настройки и запущенный backend. Не использовать production.

    $env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '..\.runtime').Path + '\browsers'
    npx playwright install chromium --only-shell
    $env:CRM_WEB_TEST_TOKEN = '<пароль отдельного синтетического стенда>'
    npm run test:e2e

По умолчанию тестовый URL `http://127.0.0.1:8001/app/`, переопределяется `CRM_WEB_TEST_BASE`. В отсутствие CRM_WEB_TEST_TOKEN используется заведомо вымышленный `synthetic-web-local`; реальный credential не коммитить. Сценарии: создание/поиск/правки/закрытие, проект и связанное уточнение, сохранение настроек через reload, конфликт конкурентной правки. Каждый выполняется на desktop и мобильном viewport. Скриншоты/трейсы только в игнорируемом `test-results`.

## Границы

Веб-правки проверяют версии и владельца; напоминание, план и дедлайн сохраняются отдельно. Изменение нескольких полей одной формы транзакционно. Для календарного ввода используется явно сохранённый пояс профиля, DST-неоднозначность отклоняется. Оригинальный срок и история остаются доступны. Месячный пользовательский лимит только уменьшает верхнюю серверную границу; пауза не включает внешние API и не отключает уже сохранённые напоминания.

Read-only почтовая синхронизация реализована с выключенным IMAP адаптером. Настройки показывают состояние/ошибки, входящие — фрагменты писем и подтверждения; сложные письма допускают ручную подготовку предложения. Синтетический стенд для `e2e/mail.spec.ts` запускается отдельной фабрикой и source worker по [docs/MAIL.md](../docs/MAIL.md). В обычной фабрике примеры не подменяют ящик. Полный E2E теперь требует этот синтетический стенд; без него можно проверять только `npx playwright test e2e/workspace.spec.ts`.

Регулярность, подтверждение плана шагов, ранний план и ограниченные предложения времени реализованы в карточке/«Сегодня»/настройках. См. [docs/PLANNING.md](../docs/PLANNING.md). Новый `e2e/planning.spec.ts` выполняется на desktop/mobile; весь набор включает 14 сценариев.

Подключение реальных аккаунтов, размещение с HTTPS/session hardening, зашифрованные backups/restore и перенос legacy остаются следующими этапами. Не объявлять промышленную готовность по локальным браузерным тестам.
