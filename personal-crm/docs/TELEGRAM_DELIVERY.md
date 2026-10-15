# Напоминания CRM в выбранный новый Telegram-бот

Владелец разрешил15октября2026 отправку напоминаний новой CRM в существующий @Technical_supp_bot, где уже нажал Start и получает технические alerts. Старый @TheVeryComfyBot, его token/receiver/сеть не изменяются. Эта настройка только исходящая: webhook и polling новой CRM выключены, команды в новом боте не принимаются. Рабочие дела задаются через веб CRM; «Напоминание» и «Срок» — разные поля. Суточная сводка использует час профиля Europe/Moscow; время можно изменить в настройках веба.

## Устройство

В compose.production.yaml уже есть delivery profile telegram. Worker использует ту же PostgreSQL очередь, проверяет состояние/версию задачи перед отправкой, фиксирует попытку до сетевого запроса. Отменённая/изменённая задача не отправляет устаревшее напоминание. При неопределённом результате задача получает unknown и автоматически не повторяется; оператор проверяет получение перед решением о повторе. Внешний Telegram не предоставляет exactly-once гарантии.

Для выбранного VPS нужен отдельный IPv6 egress: IPv4 Telegram недоступен. compose.telegram-ipv6.yaml заменяет сети только delivery на private data и собственный IPv6-only telegram-outbound; старые сети не переконфигурируются. Docker Compose >=2.33.1, IPv6 forwarding/NAT и отсутствие конфликта указанной ULA подсети обязательны. При другом сервере сначала проверить маршрут. Не отключать TLS и не подключать delivery к сети старого бота.

Токен и единственные разрешённые user/chat ID хранятся только в /etc/personal-crm/config/delivery.env, mode0600. Историческое имя CRM_TELEGRAM_TEST_TOKEN сохранено для совместимости. CRM_TELEGRAM_BOT_ID проверяется getMe перед первой отправкой. CRM_TELEGRAM_SEND_ENABLED=true должен совпадать в delivery.env и web.env; у API нет токена отправки. В ingress.env оставить webhook=false. Почта и ИИ не включаются.

## Установка и откат оператором

Сначала сохранить приватные копии конфигурации и фактические ID/image/start/restarts всех сервисов. Проверить новый bot getMe, отсутствие webhook и уже подтверждённый личный getChat. Ничего не выбирать из getUpdates: для outbound receiver не нужен. Проверить compose config --quiet с приватным deploy.env. Использовать существующий проверенный CRM_IMAGE, без schema migration и общего compose up/down.

    cd /opt/personal-crm/repository/personal-crm
    docker compose --env-file /etc/personal-crm/config/deploy.env -f compose.production.yaml -f compose.telegram-ipv6.yaml --profile telegram config --quiet
    docker compose --env-file /etc/personal-crm/config/deploy.env -f compose.production.yaml -f compose.telegram-ipv6.yaml --profile telegram up -d --no-deps api delivery

После подтверждённого running heartbeat включить delivery_required=true в приватном /etc/personal-crm/monitoring/monitor.json. deploy/ops_monitor.py дополнительно проверит running delivery, heartbeat <=180секунд, running/idle и отсутствие failed/unknown jobs. Два последовательных провала вызывают alert и внешний fail heartbeat; неизвестную доставку автоматически не переотправлять. Рутинные успешные проверки молчат.

Для отката остановить только delivery с тем же набором -f, вернуть точные private web.env/delivery.env и прежний delivery_required; пересоздать только API с --no-deps. Не удалять существующие сети/volumes и не запускать migrate. При будущих операциях delivery всегда включать IPv6 override, иначе стандартный compose заменит его сеть обратно на неработающий IPv4 egress.

## Приёмка

На15октября2026 до включения production очередь пуста, active reminders=0. Из отдельной временной PostgreSQL personal_crm_test_delivery выполнена настоящая постановка напоминания на8секунд вперёд: первый tick idle, после срока sent, следующий idle; durable Attempt success с Telegram providerID, всего1 попытка. Тестовый текст явно обозначает проверку. Временная БД удалена; рабочих задач не добавляли. Запуск delivery и окончательная проверка состояния фиксируются в EXECPLAN_TELEGRAM_DELIVERY.md. Приватный baseline/evidence: /etc/personal-crm/operator/telegram-delivery-20261015; его содержимое не публиковать.
