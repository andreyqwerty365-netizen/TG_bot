# Веб-интерфейс Personal CRM

React + TypeScript поверх существующего FastAPI/PostgreSQL. Работают Сегодня, Все дела с серверным поиском/фильтрами/страницами, Входящие с подтверждением и уточнениями, Проекты и Настройки. Данные задач не сохраняются в localStorage или отдельной клиентской базе.

## Запуск

Нужен Node.js 24. Из `personal-crm/web`:

    npm ci
    npm test
    npm run build

Из `personal-crm` задать локальные `CRM_DATABASE_URL`, `CRM_OWNER_ID`, `CRM_OWNER_TOKEN`, `CRM_TIMEZONE`, применить `python -m alembic upgrade head` и запустить:

    .venv\Scripts\python.exe -m uvicorn personal_crm.api:create_app --factory --host 127.0.0.1 --port 8001

Открыть `http://127.0.0.1:8001/app/`. Ввести именно ключ владельца `CRM_OWNER_TOKEN`, не ключ OpenAI или Telegram. После обновления вкладки войти снова: credential хранится только в памяти. Модель/почта/Telegram по умолчанию выключены. Для непрерывной обработки отдельно запустить `personal_crm.worker` и `personal_crm.source_worker` с той же БД и конфигурацией.

При разработке `npm run dev` открывает `http://127.0.0.1:5173/app/` и проксирует запросы к backend на порту 8001. Сначала запустить backend. Для другого адреса изменить локальную настройку proxy в vite.config.ts. Постоянные данные остаются в PostgreSQL.

Перед Docker build также выполнить `npm ci` и `npm run build`: Dockerfile копирует готовый `web/dist` в образ, Python wheels готовятся прежним `scripts/prepare_wheels.py`. Docker в этой Windows-сессии отсутствует, сборка контейнера не проверялась.

## Проверки

`npm test` — unit-проверки React с имитацией HTTP; они проверяют интерфейс, но не БД. `npm run build` — TypeScript и сборка. Сквозные `npm run test:e2e` используют настоящий локальный backend и PostgreSQL; не подменяют API ответами из fixtures. Нужна отдельная синтетическая БД `personal_crm_test_web`, владелец/credential из собственной тестовой настройки и запущенный backend. Не использовать production.

    $env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '..\.runtime').Path + '\browsers'
    npx playwright install chromium --only-shell
    $env:CRM_WEB_TEST_TOKEN = '<credential отдельного синтетического стенда>'
    npm run test:e2e

По умолчанию тестовый URL `http://127.0.0.1:8001/app/`, переопределяется `CRM_WEB_TEST_BASE`. В отсутствие CRM_WEB_TEST_TOKEN используется заведомо вымышленный `synthetic-web-local`; реальный credential не коммитить. Сценарии: создание/поиск/правки/закрытие, проект и связанное уточнение, сохранение настроек через reload, конфликт конкурентной правки. Каждый выполняется на desktop и мобильном viewport. Скриншоты/трейсы только в игнорируемом `test-results`.

## Границы

Веб-правки проверяют версии и владельца; напоминание, план и дедлайн сохраняются отдельно. Изменение нескольких полей одной формы транзакционно. Для календарного ввода используется явно сохранённый пояс профиля, DST-неоднозначность отклоняется. Оригинальный срок и история остаются доступны. Месячный пользовательский лимит только уменьшает верхнюю серверную границу; пауза не включает внешние API и не отключает уже сохранённые напоминания.

Подключение реальных аккаунтов, размещение с HTTPS/session hardening, почтовая синхронизация, регулярность, проверяемые зашифрованные backups и перенос legacy требуют следующих этапов. Не объявлять публикацию или промышленную готовность по локальным браузерным тестам.
