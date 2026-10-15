# Приёмка Personal CRM

## Дополнение 2026-10-15: отдельные внешние копии старого бота

По отдельному поручению владельца проверены обе legacy SQLite, вне PostgreSQL и без Telegram polling. L-B01: online backup committed WAL и обеих баз; L-B02: аутентификация, hash/schema/rows/integrity и запрет перезаписи; L-B03: S3 readback, scoped 30-day retention и сохранность прежней копии при ошибке; L-B04: изолированный download/restore; L-B05: readonly WAL wrapper и concurrent lock. Реализация/синтетические проверки — test_legacy_backup.py, процедура и фактический S3 restore — [docs/LEGACY_BACKUP.md](LEGACY_BACKUP.md). L-B06: timer enabled/active, следующий запуск 16 октября 03:20 MSK; ручной запуск именно systemd service завершился Result=success, ExecMainStatus=0 с verified_remote. Следующий календарный запуск ещё не наблюдался. Linux synthetic suite 16 passed; полный Windows suite с UTF8 и disposable PostgreSQL: 340 passed, 2 skipped (Windows POSIX/symlink).


## Генератор приватной серверной конфигурации, 15 октября 2026

Добавлены `personal_crm.deployment_setup generate/check`, тесты `tests/test_deployment_setup.py` и общая генерация файлов для `scripts/container_checks.py`. Проверены matching DB password/URL, новый owner/key, Argon2id, отключённые интеграции, отказ от перезаписи и checkout, injection/дубли/неизвестные ключи, origin/timezone/hash/key, безопасные ошибки, согласованность включённых Telegram/S3 без внешних запросов. Локально новые tests **29 passed/1 Linux-only skip**; полный backend прогон до пяти последних дополнительных cases — **320 passed/1 skip, 121.34s**, прежнее Starlette/AnyIO warning.

Финальный новый Linux run [38707830985](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38707830985) на source **ad0c56e7b61f1dd62ad49d821974d05716bd059d**: **обе jobs success**. **326 CRM passed (53.41s, без skip), 133 legacy (3.26s), 14 React, 18 desktop/mobile E2E (28.0s)**, build/pip check/migrations/restore прошли. Linux-only права 0700/0600 и запрет linked secret files проверены фактически. Первый run 38707511128 на 3a3b536 завершился cancelled после failure container job: в ней не устанавливался сам пакет CRM; исправлен editable install в единственном разрешённом root workflow.

Container rehearsal использовал файлы общего renderer, проверил их offline, затем запустил actual production images: HTTPS/local CA, Secure/HttpOnly cookie, Origin/CSRF, отключённая delivery, restart DB/API/source/Caddy с сохранёнными session/task/queue, encrypted pg_dump и isolated restore с hold/revocation/inactive reminders — **passed**. Python 3.12.15, PostgreSQL server/client 16.15, Caddy 2.11.7. Runtime local image ID `sha256:a9f49b6c40d5151038afd0ae2dfcfb30bbeaffce89ab51fe04e897d1d994a5d8`; backup `sha256:06cd1baa8b63d13014cc283f2bef486eba3c8fbd73077aa1bfa378589b036096`. Это local CI image IDs, не опубликованные registry artifacts.

Linux ASGI load: 10 000 задач/10 клиентов, p95 search **0.1291s**, today **0.2155s**, create **0.2000s**, restart persisted_without_delivery; без HTTP/TLS/VPS capacity measurement. Финальная фиксация документации не меняет runtime/config/workflow проверенного ad0c56e.

`configuration_valid` означает корректные приватные файлы, а не работающую CRM. Без настоящего VPS/домена не выполнены public HTTPS/БД/heartbeat/reboot, без согласованных отдельного Telegram/S3 — identity/delivery/backup/remote restore. Генератор не читает найденные .env/credentials, не развёртывает и не включает эти интеграции.

## Итоговый Linux CI на production patch images, 15 октября 2026

[Run 38704316507](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38704316507), source commit **91ba0dfcc460ad35bd09c66baae222ade1bd615f**: **обе jobs success**. Ubuntu 24.04.5, Python 3.12.15, Node 24.21.0, PostgreSQL server/client 16.15. **296 CRM passed (55.85s), 133 legacy (3.31s), 14 React, 18 desktop/mobile E2E (32.8s)**; TypeScript/build/pip check, migrations и реальное восстановление прошли. Одно прежнее предупреждение Starlette/AnyIO, без assertion failures.

10 000 synthetic tasks/10 clients: p95 search **0.1669s**, today **0.3191s**, create **0.2671s**; 10 100 задач и pending job пережили пересоздание API. Это Linux ASGI/PostgreSQL load без HTTP/TLS и без измерения вместимости конкретного VPS.

Контейнерная job подтвердила actual runtime Python **3.12.15**, PostgreSQL server **16.15**, backup client **16.15**, Caddy **2.11.7**, production frontend, private PG/API, HTTPS с local CA и проверкой сертификата, Secure/HttpOnly cookie, Origin/CSRF, отключённую delivery без fake claim, session/task/queue persistence после restart DB/API/source/Caddy, encrypted pg_dump и отдельный restore с hold/revocation/inactive reminders. Все созданные контейнеры/volumes удалены собственным project cleanup.

| Target | Local image content ID из этого run |
|---|---|
| runtime | `sha256:5b2eb5fedc4f477c32b59fe6cdd79a37a436ffbec0f15286b7298f882c1a8a4c` |
| backup | `sha256:51badf28c27a6147e62d99c67957300adf0e44eeee0ec7fe68a559d66725989b` |

Это идентификаторы построенных CI images, не registry-published artifacts. Для VPS собрать проверенный commit и сохранить IDs его actual build. Пакет готов к первому согласованному VPS испытанию. **Не выполнены:** public DNS/ACME, reboot VPS, настоящий внешний S3/его rehearsal, независимый monitor, реальный Telegram, перенос Amvera и production legacy import. Реальные почта/ИИ выключены. Финальная фиксация результатов меняет только документацию; код/config/workflow остаются на проверенном source commit.

## Переносимые проверки и подготовка Linux CI, 15 октября 2026

Повтор после исправления IP: [38703604939](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38703604939), commit 8aad53a, **обе jobs success**. Linux: **296 CRM (58.49s), 133 legacy (3.55s), 14 React, 18 E2E (28.8s)**, build/pip check, 10 000 задач/10 клиентов p95 0.1442/0.2330/0.2237s. Отчёт теперь правильно фиксирует Linux и фактический PostgreSQL server 16.10/client 16.15.

Production container rehearsal реально прошёл на Docker 28.0.4/Compose 2.38.2: сборка обоих targets, Caddy HTTPS с проверяемой local CA без verify=false, HttpOnly/Secure cookie, Origin/CSRF, отключённая delivery, сохранение сессии/задачи/очереди после restart DB/API/source/Caddy, реальный encrypted pg_dump/isolated restore с hold/revoked sessions/inactive reminders. Local image content IDs этого run: runtime `sha256:f84179b01d5d90ca107ed14785eb7dd2d36ab8035cd37929b2fcd74fa83f75d6`, backup `sha256:21ba83099e64ce037f937e2da555367d2eeb94264e8b184de0746087a283ea4e`. Images не опубликованы в registry и не развёрнуты на VPS.

Следующий full run проверит patch обновления production Python 3.12.15/PostgreSQL 16.15; успех указанного выше run относится к предыдущим base images. Публичные DNS/ACME, reboot VPS, реальные S3/Telegram остаются Not Run.

Первый фактический Linux run: [38702871815](https://github.com/andreyqwerty365-netizen/TG_bot/actions/runs/38702871815), commit 311fc77. Validation job **success**: Ubuntu 24.04.5, Python 3.12.15, Node 24.21.0, PostgreSQL server 16.10/client 16.15; **294 CRM (56.20s), 133 legacy (3.19s), 14 React, 18 E2E (28.3s)**, build и load прошли. Linux load p95 search/today/create 0.1450/0.2590/0.2221s; старое поле conditions ошибочно называло Windows и исправлено отдельным regression. Среда Linux подтверждена runner metadata, а не этим старым текстом.

Контейнерная job **failure**: runtime/backup images построены, migrations/init owner/init ledger выполнены, при старте Caddy обнаружен конфликт IP allocation. Исправлен production dynamic ip_range, статический Caddy IP исключён из него; доверенный proxy адрес не расширен. Повтор контейнерной проверки ещё ожидается; первый run целиком не зелёный. Локально новые два regression и предыдущие guard tests: **17 passed**. Новая локальная load проверка после metadata fix также прошла, PostgreSQL 16.10, p95 0.1327/0.2057/0.2182s; это отдельное Windows измерение.

На новом изолированном PostgreSQL наборе: **294 CRM passed, 130.55s**, **133 legacy passed, 7.21s**, **14 React unit passed**, TypeScript/build и pip check прошли. Новый `scripts/browser_checks.py` сам применил миграции, запустил собственные API/source на свободном loopback port и остановил их после **18 desktop/mobile E2E passed, 30.7s**. Старые локальные browser процессы не использовались. Из предупреждений: прежний Starlette/AnyIO и локальная Windows cache-directory permission warning; assertion failures отсутствуют.

15 новых guard/environment tests проверяют запрет рабочей/удалённой БД, разделение трёх database names, очистку унаследованных integration credentials, ограничение Docker cleanup своим project/runtime и запрет удалённого daemon. Workflow YAML/permissions/triggers и private PG/API ports проверены статически. Владелец явно разрешил один `.github/workflows/personal-crm.yml` вне модуля; workflow не развёртывает и не использует рабочие secrets.

Подготовлен отдельный контейнерный rehearsal настоящих production images, HTTPS с локальной CA, session/Origin/CSRF, restart persistence и encrypted PostgreSQL restore. Для безопасного воспроизведения production paths получили параметры с прежними defaults; Caddy routes общие для public TLS и isolated internal TLS. **Linux Docker rehearsal пока Not Run** — результат будет зафиксирован только после фактического workflow. Инструкция: [CLOUD_CHECKS.md](CLOUD_CHECKS.md). Настоящие VPS/SSH/DNS/ACME/S3/Telegram, reboot и Amvera остаются Not Run.

## Подготовка первого личного запуска, 14 октября 2026

Итог: **279 CRM passed, 123.61s**, одно прежнее предупреждение Starlette/AnyIO; **133 legacy passed, 6.16s**, **14 React unit passed**, TypeScript/Vite build прошёл. **18 desktop/mobile E2E passed, 32.0s** включают сохранённый cookie вход, capture/короткое уточнение, logout и фактический operational статус. PostgreSQL 16.10 настоящая; Python 3.12.14/Windows, только disposable databases и synthetic owners. `pip check` успешен. Core/Stage2/mail demos и 28-day simulation прошли с real_external_calls=0.

| Изменение | Проверка |
|---|---|
| Owner Argon2id/opaque cookie, expiry/logout/password rotation/hold | `test_web_sessions.py`: HttpOnly/Secure/Strict, новая вкладка, server revocation, 30 дней, no-store |
| Origin/CSRF и durable throttling | Те же PostgreSQL tests: чужой Origin, нет CSRF, 6 concurrent wrong attempts → 5×401/429, пересоздание app, отсутствие пароля в validation JSON |
| Быстрый source-first ввод/ответ/повтор после сетевого сбоя | `test_capture.py`, React capture tests, desktop/mobile `capture.spec.ts`; request identity сохраняется, конфликт текста не создаёт дубль |
| Durable operational status/readiness/queue | `test_operations.py`, React ops test, browser Settings; disabled не выдаётся за успешную delivery/копию, stale/error/backup age >26h видны |
| Production без synthetic delivery/mail/fixtures | `test_production_guards.py`, startup auth/Origin guards; выключенный transport не claim pending job; source работает без browser Bearer |
| Verified encrypted S3 workflow | `test_remote_backup.py`: synthetic object store, SDK Stubber, upload failure/readback corruption/30-day retention/restart; реальные pg_dump/download/isolated restore |
| Restore предыдущих ca294b816edf/db71 архивов и sessions fencing | `test_recovery.py`: additive missing tables в одной транзакции, sessions revoked, worker status reset, erasure/unknown guards сохранены |
| Безопасная initial setup | `test_pilot_setup.py`: пароль два раза/минимум 12, hash вместо plaintext, новый owner Москва/09:00; existing choices не перезаписываются |
| Большой backlog и persistence | `test_overview_scale.py`: обзор загружает два Task вместо 501 для undated backlog, ranking/count сохранены; отдельная load DB запрещена для normal/test_web |

Нагрузочный прогон: **10 000 synthetic задач, 10 параллельных клиентов, 100 чтений поиска/100 обзоров/100 созданий**. p95 search **0.1493s**, today **0.1815s**, create **0.2005s**, max 0.3034/0.2465/0.2683s. Пересоздание API сохранило 10 100 задач и pending job без доставки. Измерение Windows ASGI/TestClient + PostgreSQL, без HTTP/TLS, отдельная БД `personal_crm_test_load_*`; CPU/RAM VPS не измерены. Первый прогон до оптимизации не достиг цели today; его результат не скрыт в EXECPLAN_PILOT. Проверяемый CLI — `python -m personal_crm.load_rehearsal --report <private-path>`, CRM_LOAD_DATABASE_URL только новая пустая dedicated DB.

Production YAML разобран отдельным PyYAML, сверены закрытые PG/API порты, opt-in profiles, raw env_file, production guards; **это не Docker Compose/Caddy исполнение**. Docker/Linux image build, reboot, настоящий S3/Telegram, DNS/HTTPS и независимый monitoring **Not Run**. Подготовлены [пакет размещения](PILOT_DEPLOYMENT.md) и [первые пять действий](USER_GUIDE.md); этапы реального запуска/Amvera/import остаются в [плане](../EXECPLAN_PILOT.md). Реальная почта и платный ИИ выключены, действующие Amvera-боты не изменены. Ни реальные секреты, ни копии, ни результаты тестовых баз не входят в Git.

## Резервирование и пробный перенос, 14 октября 2026

**241 CRM passed, 132.55s**, одно прежнее Starlette/AnyIO предупреждение. PostgreSQL 16.10, реальные pg_dump/pg_restore/psql; **22 новых сценария** в `test_recovery.py` / `test_legacy_import.py`. **133 legacy passed, 9.74s**, старый бот не запускался. **11 React unit passed**, TypeScript/Vite build; **16 E2E passed, 53.1s** (desktop/mobile, реальный HTTP/PG). После корректировки позиции screenshot повтор экспорта: **2 passed, 3.8s**; скриншоты просмотрены. `pip check`, core/Stage2/mail demos и 28-day simulation прошли, real_external_calls=0.

| Поведение | Фактическое доказательство |
|---|---|
| AES-GCM, неверный ключ/усечение/другой тип, новый nonce | `test_encryption_authenticates_every_byte_and_randomizes_nonce`, `test_wrong_key_restore_leaves_empty_target` |
| Согласованный snapshot при concurrent write | `test_dump_counts_and_records_share_snapshot_during_concurrent_writes` — новая правка/вторая задача видны в исходной БД, восстановлена первая версия с одним делом |
| Атомарный restore/count verification и отказ непустому target | `test_count_mismatch_rolls_back_schema_and_quarantine`, `test_restore_rejects_nonempty_target_without_changing_it`, `test_restore_requires_isolated_name_and_authenticated_current_ledger` |
| Даты/evidence сохранены, отправки/paid requests не повторяются | `test_postgresql_restore_preserves_evidence_and_holds_all_delivery`, `test_restore_never_replays_paid_requests_inflight_sources_or_mail`, `test_hold_blocks_commands_mail_and_even_fresh_jobs` |
| Зарегистрированное удаление, lock, безопасная identity | `test_registered_erasure_is_reapplied_to_older_backup`, `test_erasure_ledger_lock_prevents_lost_updates`, `test_erasure_binds_owner_identity_without_sql_or_line_interpretation` |
| Daily opt-in/restart due, 30 дней, изоляция разных БД | `test_daily_backup_cycle_is_opt_in_and_checks_archive_authentication`, `test_retention_keeps_current_copy_and_ignores_foreign_files`, `test_other_database_archive_cannot_suppress_daily_backup` |
| Readonly legacy copy, timestamps/archive/repeat evidence, отсутствие отправителей | `test_preview_is_readonly_and_reports_unconverted_repeats`, `test_import_preserves_fields_and_never_starts_old_senders`, `test_imported_schedule_evidence_is_available_in_web_card` |
| Повтор/changed row/stale preview/bad date/WAL/явный timezone | Остальные три сценария `test_legacy_import.py`, PostgreSQL rollback и неизменность SQLite bytes |
| Owner-only export/hold через HTTP и browser download | `test_hold_is_visible_in_authenticated_api_and_export_is_owner_scoped`, `data-tools.test.tsx`, `data-tools.spec.ts` desktop/mobile |

Runbook/ограничения: [RECOVERY.md](RECOVERY.md). D17 **частично** реализован: encrypted snapshot/daily worker/retention/rehearsal готовы, настоящий внешний носитель/supervisor/контроль ошибок и регулярный restore не настроены. T26 выполнен на synthetic standalone SQLite, реальная разрешённая копия и production receiver switch **Not Run**. T27 выполнен на isolated PostgreSQL; потребление актуального external ledger обязательно. Удаление целого профиля поддержано, выборочная очистка задачи/письма и защита внешнего журнала от rollback **Not Run**. Docker/production/live GPT/Telegram/IMAP остаются **Not Run**. Все копии/экспорты/PID/logs стенда исключены из Git; публичные fixtures только синтетические.

## Регулярность и подтверждаемый план, 14 октября 2026

**219 CRM passed, 1 прежнее Starlette/AnyIO предупреждение, 65.06s** на настоящей PostgreSQL 16.10. **133 legacy passed, 9.22s**, бот не запускался. **9 React unit passed**, TypeScript/Vite build прошёл. **14 browser E2E passed, 20.5s**: семь сценариев на desktop и mobile, с настоящим HTTP/PostgreSQL. Реальные почта/Telegram/GPT остаются выключенными.

| Возможность | Доказательство |
|---|---|
| Выполнение экземпляра оставляет ряд, один следующий экземпляр | `test_completion_creates_one_future_occurrence_preserves_rule_and_no_deadline`, `test_two_competing_completions_create_one_instance`; browser recurring flow |
| Месячная опора, високосный февраль, пропуски без очереди | `test_calendar_anchor_and_missed_periods_do_not_create_a_backlog` (4 календарных случая) |
| DST без выдуманного сдвига, отдельная отмена/остановка | `test_dst_gap_is_visible_and_does_not_silently_shift_notification`, `test_cancel_occurrence_and_stop_series_are_different_explicit_actions` |
| Атомарность закрытия и следующего экземпляра, шаблон только для будущего | `test_next_instance_history_failure_rolls_back_completion`, `test_recurring_template_edits_leave_current_task_and_reminder_unchanged` |
| Дочерние дела только после подтверждения целого плана | `test_steps_are_drafts_until_whole_plan_confirmation_and_replay_is_idempotent`, `test_stale_plan_confirmation_cannot_promote_new_steps`; browser draft/confirm/child navigation |
| Модельная правка черновика остаётся предложением | `test_model_changes_to_existing_step_plan_require_confirmation`; реальная модель выключена |
| Ранний план сохраняет дедлайн, малый шаг не создаёт детей | `test_early_plan_requires_confirmation_and_preserves_the_external_deadline`, `test_small_step_only_starts_after_confirmation_and_does_not_create_subtasks` |
| Версии, скрытие без повторного навязывания, чужой владелец | `test_suggestion_is_version_bound_and_dismissal_is_not_regenerated`, `test_unrelated_owner_cannot_use_rules_steps_or_suggestions` |
| Предпочтительное время — по явным выборам, без переноса уведомлений | `test_adaptation_uses_explicit_choices_and_never_moves_existing_reminders`, `test_manually_selected_preference_is_not_overridden_by_adaptation` |
| Повторное «выполнил» не закрывает завтрашнее дело | `test_repeated_generic_completion_does_not_close_tomorrows_instance` |
| Сводка с единственным предложением не теряется, политика настраивается | `test_preference_only_daily_overview_is_not_silently_empty`, `test_early_planning_policy_is_server_configurable` |

Новые миграции `a8273f1d804c` и `b9184f723ade` аддитивны. Полный pytest проверил down/up/check и сохранность старых записей. Повторно прошли core demo, Stage 2 demo, 28-дневная симуляция (28 digests, 13 forgotten, 1 overdue, 1 obstacle, 3 missed, 0 auto completion, 0 external calls) и mail demo с отдельным процессом восстановления. Pip check прошёл. Скриншоты просмотрены; найденный чёрный фон native dialog воспроизведён CSS assertion в настоящем браузере и исправлен явным светлым фоном.

Точные команды и семантика: [PLANNING.md](PLANNING.md). NLP произвольного правила повторения не заявляется; правило задаётся вебом/HTTP. Live интеграции, Docker в этой Windows-сессии, encrypted backup/restore, импорт копии legacy и production-пилот не выполнялись. Следующий незавершённый объём — этап E.

## Почта без подключения реального ящика, 14 октября 2026

**197 CRM passed, 1 прежнее предупреждение Starlette/AnyIO, 48.53s** на PostgreSQL 16.10. **133 legacy passed, 8.55s**, бот не запускался. **6 React unit passed**, TypeScript/Vite build прошёл. **10 browser E2E passed, 19.6s** после перезапуска опубликованного кода, на desktop/mobile с настоящими HTTP/PostgreSQL; почтовый транспорт исключительно синтетический. Локальная фабрика для проверки явно отказывает вне test-БД и синтетического профиля.

| Возможность | Доказательство |
|---|---|
| Read-only, два независимых разрешения, INBOX/Sent без drafts | `test_real_provider_is_disabled_before_any_network`, `test_only_examine_uid_peek_and_logout_and_paginated_high_watermark`, `test_oversized_body_is_not_fetched_and_drafts_are_excluded` |
| Семь суток, источник до разбора, checkpoint только с commit | `test_seven_days_source_first_and_confirmation`, `test_rollback_does_not_advance_cursor` |
| Дедупликация, новая редакция, цепочка, старый разбор | `test_replay_revisions_supersede_pending_proposal`, `test_obsolete_source_cannot_recreate_a_superseded_proposal`, `test_reply_before_confirmation_replaces_the_suggestion` |
| UIDVALIDITY, ограниченная сверка, порядок MIME response | `test_uidvalidity_reset_and_deleted_metadata_are_reported`, `test_uidvalidity_reset_rebinds_tracked_old_message_by_message_id`, `test_busy_inbox_does_not_starve_sent_folder`, `test_server_may_return_uid_after_the_body_literal` |
| Изменение срока/отмена без автоматической записи в task | `test_reply_proposes_deadline_and_cancel_without_mutation`, `test_flag_changes_and_removal_do_not_reanalyse_or_cancel` |
| Sent — предложение обещания, не выполнение | `test_sent_promise_and_reply_do_not_complete_the_task`; browser evidence показывает предупреждение |
| Ошибка доступа, ограниченные повторы, конкурентный запуск и отключение | `test_backoff_bounded_auth_and_disconnect`, `test_parallel_sync_and_expired_lease`, `test_disconnect_fences_out_inflight_and_error_visible_in_overview` |
| Evidence, ручной просмотр, версия/owner, без активных задач до подтверждения | `test_sync_status_evidence_and_explicit_confirmation`, `test_manual_review_is_still_only_a_proposal`, `test_owner_scope_and_version_conflict_on_mail_proposal`, `test_dismiss_review_does_not_create_or_delete_any_task`, `web/e2e/mail.spec.ts` |
| HTML/вложения, семидневная очистка без потери pending | `test_html_is_text_attachments_are_flagged_and_no_remote_fetch`, `test_irrelevant_cache_expires_but_evidence_remains`, `test_retention_does_not_destroy_an_unprocessed_source`, React `mail.test.tsx` |
| Старое письмо для просмотра остаётся видно среди новых нерелевантных | `test_old_review_is_not_hidden_by_newer_irrelevant_mail` |

`python -m personal_crm.mail_demo` выполнен: `saved=3 proposals=2 tasks_before_confirmation=0 tasks_after_confirmation=1 real_external_calls=0`. Сохранённые источники подобрал новый Python-процесс `source_worker --once`. `mail_worker --once` с обоими разрешениями false выдал `outcome=disabled`. Полный pytest проверил аддитивную миграцию `f5029a13c47b`, downgrade/upgrade/check и сохранение исходных записей. Pip check прошёл. Скриншоты desktop/mobile просмотрены.

Команды и точные ограничения: [MAIL.md](MAIL.md). Живой IMAP/OAuth, права конкретного провайдера, NLP-качество, Docker на этой машине, production, backup/restore и legacy import не проверялись. Срочная почтовая инициатива до сводки пока не добавлена (D09); предложения доступны в вебе и следующей сводке в прежних лимитах. Консервативные локальные правила не объявляются полноценным NLP.

## Веб и окончательная проверка продолжения, 14 октября 2026

**165 CRM passed, 1 прежнее Starlette/AnyIO предупреждение, 39.04s** на настоящей PostgreSQL 16.10/Windows/Python 3.12. **133 legacy passed, 7.96s**, бот не запускался. **3 React unit passed**, TypeScript/Vite build прошёл. **8 browser E2E passed**: четыре сценария на desktop и на мобильном viewport, HTTP действительно идёт в локальный FastAPI/PostgreSQL без mock API.

| Рабочая возможность | Доказательство |
|---|---|
| Произвольное ручное дело без включения модели, повтор HTTP без дубля | `test_manual_create_search_detail_and_idempotency`; browser create/search/edit/close |
| Поиск, страницы, фильтры состояния/типа/источника/проекта/срока | `test_workspace_filters_pagination_and_sql_wildcards`, `test_deadline_filters_use_current_time_and_stored_timezone`, `test_unicode_case_insensitive_search` |
| Отдельные deadline/plan/reminder, дата или точный момент по поясу | `test_workspace_edit_versions_and_separate_fields`, `test_deadline_local_distinguishes_date_and_instant`, `test_multi_field_web_edit_rolls_back_on_invalid_time` |
| Проекты, привязка задач, отказ для чужих объектов | `test_projects_group_tasks_and_reject_foreign_objects`; browser project survives reload |
| Входящие, связанный короткий ответ | `test_inbox_clarification_reply_uses_real_context`; browser clarification |
| Настройки сохраняются и проверяют version | `test_settings_survive_new_requests_and_conflicts`; browser reload |
| Пауза/снижение бюджета стоят до SDK, не включают провайдера | `test_preferences_can_pause_ai_and_cap_budget_without_enabling_provider`, `test_owner_preferences_block_paid_request_before_client_creation` |
| Конкурентные веб-правки не затирают новые | browser stale edit; API version conflicts |
| Источник после уточнения и ровно одно конкурентное создание | `test_edit_original_after_short_clarification_keeps_one_task`, `test_concurrent_answers_resolve_creation_once` |
| Безопасные заголовки, no-store и приватность поиска в журнале | `test_web_requests_have_browser_security_headers`, `test_access_log_excludes_search_text`; React не пишет credential в local/sessionStorage |

Миграции `c51d46c71af0`, `d721cde40377`, `e41978d2ab67` аддитивны; full pytest проверяет down/up/check и сохранение исходных записей. Core/Stage 2 demo, 28-дневная симуляция и pip check повторно прошли. Скриншоты desktop/mobile просмотрены; исправлены видимость всех пяти мобильных разделов и возврат фокуса после dialog. Локальный React bundle 260.41 kB JS (79.65 kB gzip) и 15.22 kB CSS; это размер сборки, не измерение сетевого p95.

Не выполнены: реальная почта, live GPT/Telegram, независимые NLP-метрики, Docker image/Compose на этой машине, production, зашифрованные внешние backup/restore и legacy import. Ключи интеграций не подключались; модельные проверки используют официальный SDK с синтетическим HTTP. Следующие этапы C/D/E остаются открыты. Входящий/исходящий Telegram receiver не переключался.

## Продолжение: шесть критических регрессий, 14 октября 2026

Новый независимый прогон на Windows/Python 3.12/PostgreSQL 16.10: **145 passed, 1 прежнее предупреждение, 29.87s**. Включает все прежние 124 теста и 21 новый сценарий в `tests/test_continuation_regressions.py`. До исправлений воспроизведены ложное завершение, пропуск короткого времени, ограничение старых задач, неверное поле edit и заблокированный unbilled retry. Результаты предыдущих прогонов ниже остаются историческими.

| Сценарий | Доказательство |
|---|---|
| «Резюме не обновил», «Резюме обновил?» и четыре варианта | `test_uncertain_completion_keeps_task_and_reminder`: задача, версия, reminder и история сохранены |
| «в 19:00» после уточнения, рестарта и полуночи | `test_time_only_answer_uses_saved_date_after_restart_and_midnight`; неверные часы не теряют дату |
| Поиск старого дела среди 111 задач | `test_subject_search_finds_old_task_beyond_65_rows`, `test_last_cursor_finds_old_reminder_outside_recent_candidates` |
| Сбой до разбора, истечение lease, временная ошибка | `test_recovery_picks_pending_source_without_telegram_replay`, `test_recovery_reclaims_expired_parse_after_restart`, `test_transient_processing_failure_recovers_with_bounded_backoff`, `test_recovery_cli_runs_in_new_process` |
| Edit времени и одновременная правка названия | `test_edit_reminder_changes_reminder_after_confirmation`, `test_edited_title_and_time_apply_together_only_after_confirmation` |
| Неоплаченный отказ и потенциально оплаченный timeout | `test_known_unbilled_provider_error_allows_explicit_retry`, `test_rate_limit_automatically_retries_once_after_backoff`, `test_uncertain_paid_request_never_repeats_in_recovery` |
| Ограниченные повторы и точная привязка вопроса | `test_permanent_processing_failure_stops_automatic_retries`, `test_explicit_reply_finds_question_beyond_context_cap` |

Миграция `b63125ff910a` аддитивна; full pytest проверил down/up/check и сохранение старых записей. Core demo, Stage 2 demo, 28-дневная симуляция и pip check прошли. Настоящие Telegram/почта/GPT, production и Docker Compose на этой Windows-машине **Not Run**; никаких платных или внешних продуктовых вызовов не выполнялось.

Актуальный Stage 2, 14 октября 2026 года: **124 passed, 1 warning in 19.15s** на настоящей PostgreSQL 16.10; включает прежние 69 и 55 новых проверок. **133 legacy passed in 1.07s**. Официальный SDK работает с mocked HTTP; live GPT/Telegram и независимая оценка NLP **Not Run**. Исторические результаты ядра ниже сохранены с датами.

## Stage 2: пятнадцать обязательных сценариев

| № | Реально выполненное доказательство | Граница результата |
|---|---|---|
| 1 | test_owner_exact_reminder_committed_without_second_confirmation; Stage 2 HTTP smoke | Одна задача + exact по IANA, без proposal; synthetic Update |
| 2 | test_free_obligation_waiting_forward_old_relative_and_note_not_invented | Undated задача, прежние rotation tests/симуляция |
| 3 | тот же тест | Forward request без исполнителя уточняется |
| 4 | тот же тест; stage2_demo | Чужое обещание — waiting |
| 5 | тот же тест; test_ambiguous_or_invalid_calendar_does_not_schedule | Старые relative, до пятницы/23 числа не получают угаданный срок |
| 6 | test_existing_reminders_survive_disabled_ai_and_repeat_cancel; HTTP smoke | Source-bound completion, pending repeat отменён |
| 7 | тот же тест; test_date_clarification_bound_across_restart_and_unrelated_input | Изменён reminder, исходный deadline сохранён |
| 8 | test_completion_unique_subject_move_reminder_only_and_overview; прежние overview/policy tests | On-demand обзор не расходует инициативы |
| 9 | test_model_proposal_yes_no_and_stale_object_binding; test_dialogue_expiry_and_stale_target_reject_change | Устаревший yes/date не переписывает task |
| 10 | test_update_duplicate_message_repeat_forward_and_edits; test_replayed_update_resumes_after_source_receipt_commit_crash | Повтор receipt/revision идемпотентен, новая forward отдельна; replay восстанавливает pending source |
| 11 | test_webhook_secret_user_chat_and_default_disabled; HTTP smoke | Bearer, constant-time secret, user/chat allowlist; нет данных при отказе |
| 12 | test_sender_forward_injection_cannot_execute_commands; test_provider_schema_has_no_authority_or_arbitrary_actions; прежние mail/foreign-owner tests | Модель/forward не дают command authority |
| 13 | test_provider_failures_preserve_source_and_do_not_retry; test_sdk_error_leaves_preexisting_queue_functional; test_existing_reminders_survive_disabled_ai_and_repeat_cancel | Disabled/refusal/incomplete/timeout/JSON/date/auth сохраняют source, reminders независимы |
| 14 | test_concurrent_requests_cannot_overspend; test_80_100_thresholds_and_utc_month; test_missing_gate_never_constructs_sdk | PostgreSQL row locks, upper reservation, zero retries, cache; реальные траты не выполнялись |
| 15 | Полный pytest 124; legacy 133; demo/simulation; scripts/smoke_http.py и smoke_stage2_http.py | Настоящие PostgreSQL, Docker/Uvicorn/worker; всё synthetic/fake/mocked |

Дополнительно: долговечная дата/yes после нового service, 24-часовое expiry, несвязанная фраза включая parse error, bounded candidates, source trust при edit, reply на recorded bot message, голос без ложного анализа, plain-text getMe/sendMessage и unknown без resend. Calendar SDK значения сверяются с датой/часами источника независимо от корректности JSON. Новые plan/return/focus предложения применяются после yes; draft_steps не назначают обязательства.

O-T01–O-T06/O-T08 закрыты на локальном стенде в объёме источников, политики, очереди, бюджета и mocked SDK/HTTP (соответственно строки 13/14/12/10). O-T07: secret поля repr=False, тексты ошибок ограничены кодами, SDK payload минимален, статический scan перед commit; настоящие private данные/провайдерские журналы/клиентская сборка не проверялись. O-T06 расход проверен консервативными synthetic ценами и concurrency, не счётом реального провайдера.

Точная команда: `CRM_TEST_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test .venv/bin/python -m pytest -q --tb=short`. Baseline перед изменением: 69 passed in 10.75s. Предупреждение Starlette TestClient/AnyIO одно, без skipped/xfail. Миграционные down/up/check и сохранение прежних записей входят в набор; текущая Stage 2 миграция применена также к сохранённой отдельной Compose БД. Test-bot/AI параметры по умолчанию отключены.

Демо ядра подтвердило отдельные процессы чтения/доставки, source/dedupe/mail/close. Stage 2 demo: fake_replies=7, fake_exact_delivery=1, durable dialogue, отменённый repeat. Simulation: 28 дней/28 digests/13 undated представлений/1 overdue/1 obstacle/3 consolidated missed jobs/0 automatic completions/0 external calls. Образ offline собран из 34 locked wheels с SHA256; оба настоящих HTTP smoke прошли после обновления схемы/контейнеров. Все команды запуска находятся в README, аудит в STAGE2_AUDIT.md.

144 синтетических примера в fixtures/stage2_corpus.json, 108 development/36 held_out, документация разметки STAGE2_CORPUS.md. Корпус не прогонялся через реальную модель, показатели 95%/90% **Not Run**. Также Not Run: live Telegram/GPT/почта, нагрузочный p95, production migration/receiver switch, encrypted backup/restore, регулярные задачи, полный UI и production-пилот. Эти ограничения Stage 2 не выдаются за пройденную приёмку.

Исторический статус ядра 13 октября 2026 года (актуальные доказательства Stage 2 ниже): проверено первое изолированное ядро на настоящей PostgreSQL с контролируемыми fake-адаптерами. Частичная проверка не означает готовую Telegram/почтовую/OpenAI-интеграцию. Реальное качество модели не проверялось. Команды, результаты и границы приведены ниже.

## Матрица исходных требований

| ID | Проверка | Ожидаемое поведение | Статус |
|---|---|---|---|
| T01 | Однозначная задача одной фразой | Создаётся один раз без формы, подтверждение соответствует данным после commit. | Stage 2: ограниченная русская грамматика — test_owner_exact_reminder_committed_without_second_confirmation, test_free_obligation_waiting_forward_old_relative_and_note_not_invented; общий NLP Not Run |
| T02 | Задача без дедлайна | Сохраняется без выдуманной даты и обязательного вопроса о сроке. | Ядро проверено — test_create_without_deadline_commits_history |
| T03 | Недостаточно контекста | Источник сохранён, задан существенный вопрос, другие сообщения принимаются. | Частично: fake-уточнение и независимый ввод — test_waiting_and_unknown_old_relative_date |
| T04 | Сбой ИИ после получения | Источник не потерян, нет ложного «задача создана». | Ядро проверено — test_source_committed_before_failure_and_retry |
| T05 | Сбой БД | Нет ложного подтверждения сохранения. | Ядро проверено — test_task_history_queue_atomic_rollback (реальный отказ PostgreSQL), test_database_error_never_acknowledged (HTTP ошибка) |
| T06 | Повтор технического события | Нет второй задачи и повторного применения команды. | Ядро проверено — test_technical_dedup_and_account_scope, test_concurrent_source_retry_creates_once |
| T07 | Повторная ручная пересылка похожего дела | Нет ошибочного объединения только по совпадению текста. | Ядро проверено — test_identical_manual_forwards_are_distinct |
| T08 | Старая пересылка со словом «завтра» | Не рассчитывать срок от сегодняшнего дня; учесть оригинал и неоднозначность. | Stage 2: old relative forward уточняется, владелец использует received_at/IANA — test_free_obligation_waiting_forward_old_relative_and_note_not_invented, test_ambiguous_or_invalid_calendar_does_not_schedule |
| T09 | Чужое обещание прислать документ | Ожидание или уточнение, не задача владельцу отправить документ. | Stage 2: ограниченная грамматика forward promise -> waiting; остальные сложные фразы требуют gated GPT/уточнение, качество GPT Not Run |
| T10 | Новое обязательство из письма | Сначала предложение, активное дело только после подтверждения. | Ядро проверено — test_mail_only_proposal_confirmation_and_rejection; настоящий ящик не подключён |
| T11 | Письмо/пересылка с командой удалить задачи | Не исполнять как команду владельца. | Ядро проверено — test_forbidden_model_operation_never_applied, test_untrusted_update_only_proposes_and_stale_confirmation |
| T12 | Явная команда перенести напоминание | Без повторного подтверждения, дедлайн неизменен. | Ядро проверено — test_reminder_move_preserves_original_deadline, test_http_reminder_and_close; явная HTTP-команда |
| T13 | ИИ предлагает перенести срок | До подтверждения действующие значения сохранены. | Ядро проверено — test_deadline_ai_change_is_pending_until_confirmation |
| T14 | Запоздалое «да» после другой правки | Проверить версию и связь, не применить устаревшую правку. | Stage 2: durable yes + proposal/task version — test_model_proposal_yes_no_and_stale_object_binding, test_failed_unrelated_phrase_does_not_capture_old_unbound_yes |
| T15 | Лимит уведомлений | Одна сводка, не больше двух инициатив в сутки, минимум 4 часа между ними; явные точные напоминания по D04. | Ядро проверено — notification cap/gap, test_parallel_initiatives_reserve_budget_under_owner_lock, test_four_week_simulation_keeps_rotation_and_daily_budget, test_delivery_crossing_profile_midnight_is_counted_on_actual_send_day |
| T16 | Нет ответа на напоминание | Не больше одного повтора через 4 часа при актуальности и свободном лимите. | Ядро проверено — test_send_restart_repeat_once_and_close, test_exact_exempt_repeat_consumes_limit |
| T17 | Выполнение до повтора | Старый повтор не отправляется. | Ядро проверено — test_close_before_repeat_cancels, test_close_before_initial_send_cancels |
| T18 | Три переноса плана выполнения | Один раз предложить разбор, переносы уведомлений не засчитываются. | Ядро проверено — test_plan_moves_count_without_changing_deadline, test_obstacle_prompt_once_not_daily_and_no_auto_state_change; вопрос не выбирает действие за владельца |
| T19 | Просрочка | Исходный срок сохранён, нет одинакового отдельного предупреждения каждый день. | Ядро проверено — test_overdue_announcement_once_and_original_deadline_retained, test_full_initiative_budget_reports_overdue_in_digest_once, test_reminder_move_preserves_original_deadline |
| T20 | Регулярная задача | Закрытие экземпляра не отменяет следующие периоды. | Проверено на PostgreSQL/HTTP и desktop/mobile E2E: completion/cancel экземпляра, отдельный stop, monthly/leap/DST, конкуренция/rollback; разговорное создание произвольного правила Not Run |
| T21 | Перезапуск/остановка обработчика | Сохранённые задания восстанавливаются, устаревшее не отправляется массово. | Ядро проверено — lease/fencing/SKIP LOCKED, test_outage_consolidates_old_exact_reminders_and_keeps_tasks, test_two_workers_consolidate_one_outage_report; реальные каналы не подключены |
| T22 | Неопределённый исход отправки | Честное состояние, не бесконечные повторы. | Ядро проверено — bounded retries/unknown, test_crash_during_digest_reservation_does_not_resend_one_time_question, test_closing_after_crashed_intent_keeps_unknown_outcome_instead_of_pending_forever |
| T23 | Пояс с сезонным переводом времени | Даты и сводка по политике профиля, без дублей; неизвестный пояс не заменяется серверным. | Stage 2: relative/IANA и DST gaps/folds проверены — test_dst_gap_fold_and_unknown_timezone_ask; миграция пользовательского пояса остаётся отдельно |
| T24 | Отозван почтовый доступ | Видна ошибка синхронизации, не ложное «новых дел нет». | Проверено на синтетическом IMAP/HTTP/PostgreSQL — test_backoff_bounded_auth_and_disconnect, test_disconnect_fences_out_inflight_and_error_visible_in_overview; живой ящик не подключён |
| T25 | Достигнут бюджет ИИ | Новые платные обращения блокируются, базовые задачи/напоминания работают. | Stage 2: PostgreSQL budget gate/80/100/concurrency с настоящим SDK и mocked HTTP — test_concurrent_requests_cannot_overspend, test_80_100_thresholds_and_utc_month; платных вызовов нет |
| T26 | Миграция старого бота | Сверены записи/сроки/повторы, тренировки целы, нет двух отправителей. Производственную миграцию пока не выполнять. | Synthetic standalone SQLite → PostgreSQL проверено: notes/done/archive/UTC/repeat evidence/idempotence/rollback; routine bytes целы, sender/jobs отсутствуют. Реальная копия/production Not Run |
| T27 | Восстановление копии | Данные/доступ/расписание проверены, нет массовой повторной отправки, учтены зарегистрированные удаления. | Проверено настоящим pg_dump/restore/psql в isolated БД: count verification/rollback, owner hold, schedules выключены для ручной проверки, unknown/paid не replay, external ledger повторно удаляет профиль. Off-server/регулярный rehearsal Not Run |
| T28 | Посторонний пользователь | Не читает и не меняет данные через бот или веб; пустая конфигурация владельца не открывает доступ. | Ядро проверено — test_owner_api_and_connector_authentication, test_missing_owner_fails_closed, test_object_owner_and_versions_checked, test_confirmation_other_owner_refused |

## OpenAI API

| ID | Проверка | Ожидаемое поведение | Статус |
|---|---|---|---|
| O-T01 | Нет ключа | Существующие задачи доступны, напоминания работают. | Stage 2: test_missing_gate_never_constructs_sdk, test_sdk_error_leaves_preexisting_queue_functional; PostgreSQL + fake worker |
| O-T02 | Ключ неверен/отозван | Ошибка без раскрытия секрета, источник сохранён. | Stage 2: unauthorized mocked SDK -> safe ai_auth_error, source persisted — test_provider_failures_preserve_source_and_do_not_retry |
| O-T03 | Ошибка/тайм-аут/отказ/неполный ответ | Нет ложного создания/изменения. | Stage 2: timeout/refusal/incomplete/invalid JSON/source проверены реальным SDK с mocked HTTP, без ложного task ack |
| O-T04 | JSON валиден, смысл/дата/действие нет | Автоматическое применение блокируется. | Stage 2: wrong_date/invented_time/command/foreign source отклоняются; test_calendar_values_verified_independently_of_valid_json |
| O-T05 | Инструкция в письме изменить другие задачи | Не расширяет полномочия. | Stage 2 + ядро: forward/mail authority и foreign-owner tests; strict output не содержит command |
| O-T06 | Исчерпан лимит | Новые платные запросы остановлены, напоминания продолжаются; параллельные запросы учитываются. | Stage 2: concurrent reservations, 80/100%, unknown charge/UTC month; очередь независима от API |
| O-T07 | Сборка и журналы | Ключ не попадает в исходники, клиентскую сборку и логи. | Частично: synthetic-only secret scan/минимальный SDK payload/безопасные коды ошибок, реальные private журналы Not Run |
| O-T08 | Технический дубль источника | Нет лишнего платного разбора/повторной операции. | Stage 2: source cache/SDK request count=1, Update duplicate, unknown no paid retry; всё mocked |

## Дополнительные проверки полноты переноса

Проверить отдельно: сводка до трёх главных задач; ротация одной-двух забытых задач без срока без вытеснения остальных; отсутствие пустой сводки; черновые подшаги без навязанных сроков; отвлечённое сообщение не закрывает все ожидающие ответы; изменение источника имеет версию; отмена последней операции не затирает более позднюю правку; план выполнения и возврат после откладывания не меняют дедлайн; изменение времени ИИ без подтверждения запрещено.

Для почтового адаптера: первичные 7 дней, затем инкрементальная сверка; надёжная контрольная точка; восстановление просроченной контрольной точки; чтение без отправки/изменения; безопасный HTML; отсутствие автоматической загрузки внешних картинок; очистка временного кэша через 7 дней; недоступное вложение не считается прочитанным. Для веба: единая база с Telegram, защита владельца/сессий, конкурентные версии, поиск и экспорт.

## Требования к качеству модели

Подготовить минимум 120 размеченных русскоязычных синтетических примеров: явные команды, пересылки, письма, разговорный ввод, опечатки, отмены, относительные даты, несколько действий в сообщении, отсутствие обязательства. Оставить независимую проверочную часть, не подбирать промпт по ней.

Исходные цели: не менее 95% корректных автоматических созданий на проверочном наборе и не менее 90% автоматической обработки заранее размеченных однозначных команд. Считать отдельно точность, долю уточнений и пропуски обязательств: нельзя формально улучшать точность, спрашивая обо всём. Полномочия проверять независимо от оценки модели. Нулевое число ошибок в тестах не является гарантией их невозможности.

Fake-модель проверяет маршрутизацию и политику, но не доказывает качество распознавания GPT. При отсутствующих ключах/бюджете реальные модельные испытания пометить как не выполненные.

## Проверки эксплуатации

Для сохранённых локально напоминаний цель начала отправки при доступных сервере/провайдере: не более 60 секунд в 95% испытаний. Для простых операций без ИИ: ответ не более 2 секунд в 95% испытаний при нагрузке одного пользователя. Внешние сбои учитывать отдельно.

Проверить на настоящей тестовой PostgreSQL транзакции, блокировки, параллельных обработчиков, прерывание после сохранения источника, прерывание после захвата задания, восстановление истёкшего владения, рестарт с той же БД. SQLite и in-memory mock не заменяют эти проверки. Не обещать exactly-once доставку через Telegram при неопределённом сетевом результате.

Перед выпуском: зашифрованная резервная копия и проверенное восстановление; владелец и отказ постороннему; миграция только копий с отчётом и отдельным разрешением на переключение; один действующий Telegram-приёмник; один отправитель; журнал без личных текстов/ключей.

После технической приёмки пилот: ложные задачи, исправленные даты, пропущенные сообщения, переносы и объём ручных действий. Настройки полезности можно корректировать, полномочия нельзя автоматически ослаблять.

## Формат доказательств

Для каждого реализованного этапа добавить команду, окружение, фактический результат, пути тестов и ограничения. Число прошедших тестов записывать после запуска. Непроведённые проверки не отмечать зелёными и не скрывать за словом «готово». Первое облачное задание может закрыть только часть матрицы; оставшаяся часть должна сохраняться в плане.

## Трассировка пользовательских требований R01–R19

Реальный Telegram/NLP не подменяется fake-fixture. «Ядро» означает проверку сохранения/политики с контролируемой интерпретацией на PostgreSQL.

| ID | Реализация / доказательство / оставшийся объём |
|---|---|
| R01 | POST /sources, T01–T02; controlled fixture. Ограниченный русский Update-ввод в Stage 2; общее NLP Not Run. |
| R02 | channel=forward и отдельные external_id; T07. Изолированный Update adapter есть, live receiver выключен и Not Run. |
| R03 | obvious create либо предложение/уточнение; T03, T07. Смысловое качество не проверялось. |
| R04 | MailSync/source worker создают только proposals/review; T10, mail demo и browser подтверждают отсутствие задачи до «Принять». |
| R05 | Неизвестная fixture вызывает уточнение без блокировки другого ввода; T03. |
| R06 | Любой propose_update ждёт подтверждения; T13–T14. |
| R07 | Explicit HTTP commands исполняются сразу после проверки версии; T12, T17. Ограниченные разговорные команды/версии проверены в Stage 2. |
| R08 | Модельные draft_steps остаются черновиком; изменение существующего плана только через подтверждение, весь набор дочерних задач создаётся отдельным явным решением. Tests stage D + SDK fixtures; NLP качество Not Run. |
| R09 | Ручные настройки и версия профиля; ограниченное предложение предпочтительного времени по трём явным выборам. Только подтверждение, существующие уведомления и лимиты не изменяются. |
| R10 | Quiet hours отсутствуют; Worker/policy. Настоящей доставки нет. |
| R11 | Три main, сроки, forgotten, waiting, proposals/guidance; T15. Внешняя доставка только fake. |
| R12 | Все дедлайны в overview; ранний план и малый шаг предлагаются локально, применяются после подтверждения, deadline сохраняется. test_early_plan_requires_confirmation_and_preserves_the_external_deadline, test_small_step_only_starts_after_confirmation_and_does_not_create_subtasks. |
| R13 | Единственный repeat через 4 часа, T16–T17. |
| R14 | Счётчик поздних plan-переносов, один вопрос после каждых трёх; T18. Уменьшение шага автоматически не выполняется; разговорный ответ ещё не реализован. |
| R15 | Ротация двух undated задач по успешному представлению/обсуждению; test_successful_digest_rotates_forgotten_manual_overview_changes_nothing и 28-дневная симуляция. |
| R16 | Объяснимый порядок focus/сроки/просрочки/план/forgotten, main не больше трёх, полный обзор отдельно; test_overview_ranks_focus_preserves_all_deadlines_and_separate_dates. |
| R17 | Одно событие согласованного срока, инициатива либо digest, далее только статус просрочки; T19. Unknown не даёт повторного объявления. |
| R18 | Проверено 28 дней сохранённого сопровождения без ложного выполнения. Реальные каналы и разговорные ответы остаются следующими этапами. |
| R19 | Интерфейс Interpreter и закрытый real_ai; внешние платные вызовы отсутствуют. Responses strict SDK и PostgreSQL ledger реализованы, реальные вызовы/качество Not Run. |

## Трассировка решений D01–D17

| ID | Реализация / доказательство / оставшийся объём |
|---|---|
| D01 | Profile.digest_hour=12, ensure_digest; test_digest_one_per_day_empty_and_stale. |
| D02 | Явный IANA-пояс профиля; неизвестный пояс запрещает инициативы/сводку. Импорт legacy/первый вход не реализованы. |
| D03 | Единственный repeat через 4 часа; test_send_restart_repeat_once_and_close. |
| D04 | Exact вне лимита, repeat внутри; test_exact_exempt_repeat_consumes_limit. |
| D05 | Local day и межполуночный gap; test_policy_gap_crosses_midnight_and_dst. |
| D06 | Счётчик только поздних переносов существующего planned_on; reminder и молчание не учитываются — test_plan_moves_count_without_changing_deadline. |
| D07 | IMAP SSL adapter, явные INBOX/Sent, readonly EXAMINE/BODY.PEEK, исключение Draft/Deleted/Junk; protocol tests. Реальный ящик не подключён. |
| D08 | Семь суток, PostgreSQL checkpoint/lease, revision/thread dedupe и UIDVALIDITY recovery; test_mail_sync.py/test_mail_imap.py. |
| D09 | Digest показывает число pending proposals; приоритет срочного письма не реализован. |
| D10 | Внешний календарь не подключён; внутренние события следующий этап. |
| D11 | Default fake; отдельный test-bot TelegramTransport проверен mocked HTTP, live/web push Not Run. |
| D12 | До 12 черновых шагов; одно подтверждение текущей версии создаёт весь набор детей без придуманных сроков. Replay request_id не дублирует набор. |
| D13 | kind=note/task/waiting и отсутствие придуманного дедлайна; T02/T09. Общая классификация fake-моделью не доказана. |
| D14 | Серверная привязка владельца, deny by default; T28. |
| D15 | Реальные AI/почта/Telegram выключены. IMAP требует enabled+read consent до создания клиента; test_real_provider_is_disabled_before_any_network. Live/paid calls не выполнялись. |
| D16 | Очистка обработанного кэша через 7 суток, ограниченный evidence остаётся с pending/accepted; необработанные источники сохраняются. test_irrelevant_cache_expires_but_evidence_remains, test_retention_does_not_destroy_an_unprocessed_source. |
| D17 | Частично: AES-256-GCM snapshot, opt-in daily cycle, retention 30 дней, isolated restore/counts/hold/erasure ledger проверены. Фактический внешний mount/supervisor/monitoring и регулярный rehearsal не настроены; RPO 24h в production не заявляется. |

## Фактическое окружение и команды первого ядра

Python 3.12, PostgreSQL 16.10 в отдельном контейнере, Docker 28.4.0, фиксированные direct/transitive зависимости в requirements.lock. Из `personal-crm/`:

    CRM_TEST_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test .venv/bin/python -m pytest -q

Фактически выполнены **42 теста, без skipped/xfail, 5.06s** на PostgreSQL. Есть одно предупреждение DeprecationWarning совместимости Starlette TestClient/AnyIO, не ошибка тестов. Набор включает upgrade/downgrade/upgrade/check Alembic и реальное ограничение PostgreSQL, откатывающее изменение task/history/job одной транзакцией. Миграционный downgrade проверялся только на disposable test DB.

    CRM_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test .venv/bin/python -m personal_crm.demo

Dемо проходит: source_persisted, duplicate_applied_once, fake_delivery_attempts=1, closed_repeat_cancelled, mail_proposal_confirmed; real_external_calls=0. Чтение после «рестарта» и доставка выполняются отдельными Python-процессами. Демо использует уникальный профиль и не очищает прежние записи.

Контейнер собран через `scripts/prepare_wheels.py` и `docker build --build-context crm_wheels=.runtime/wheels -t personal-crm:dev .`. TLS не отключалась; SHA256SUMS проверены внутри offline build. Устранены ограничения DNS внутри Docker и права чтения исходников непривилегированным пользователем образа. Compose поднимает отдельную PostgreSQL, Alembic, API и worker. `scripts/smoke_http.py` фактически проверил readiness, отказ без credentials, source, reminder, фоновую fake-доставку и close/cancel. Настоящий HTTP-запрос проверяет работающий Uvicorn/worker, не только TestClient.

Из корня репозитория `/workspace/.tg-bot-venv/bin/python tools/run_tests.py -q`: **133 passed in 1.37s**. Корневой бот не запускался. Изменения source/config/test файлов только внутри personal-crm.

Не выполнены: настоящие внешние каналы, paid OpenAI, независимый корпус 120 примеров, нагрузочные SLO/p95, production-миграция, encrypted backup/restore и пилот. В исходном ядре были непроверены T18/T20/T24/T26/T27, O-T02/O-T06. Текущая итерация закрыла проверки ядра T18/T19/T21; T20/T24/T26/T27 и O-T02/O-T06 остаются не проверены. T23/T25 остаются частичными.

После финальной сборки выполнены настоящий `docker compose restart crm-db` и повторный HTTP smoke. PostgreSQL сохранила выполненную задачу, успешную delivery attempt и отменённый repeat; worker/API восстановили подключение. Демо выполнено два раза подряд с новой синтетической областью каждого запуска, оба успешны. Изоляция diff и secret scan подтверждены перед коммитом. Ветка `codex/personal-crm-core` отправлена в GitHub; создание PR через GraphQL API не выполнено из-за ответа Forbidden (403).

## Фактическая проверка продолжения: сопровождение

Из `personal-crm/` прежней командой pytest на PostgreSQL 16.10: **69 passed, 1 warning in 12.05s**, без skipped/xfail. Новые проверки в `tests/test_accompaniment.py` и дополнения API/transactions включают plan/defer/resume/cancel/focus, отказ без пояса, границу календарной даты, ротацию и ранжирование, один вопрос после трёх переносов, предупреждение просрочки в инициативе/сводке, неизвестный исход/потерянный intent, агрегирование простоя и два конкурирующих обработчика. При восстановлении ещё не отправленного старого срока событие используется повторно; уже объявленный либо неопределённый исход не повторяется.

Миграция `9b0fd1794927_task_accompaniment` аддитивна. `test_additive_upgrade_preserves_existing_core_records` вставляет записи в схему предыдущего коммита, применяет upgrade и сверяет данные/defaults. Проверки down/up/check используют только disposable PostgreSQL; порядок удаления constraints/FK исправлен по фактическим сбоям первого прогона. `test_obstacle_and_plan_history_rollback_together` доказывает атомарность нового счётчика, вопроса и истории при отказе БД.

    CRM_DATABASE_URL=postgresql+psycopg://crm_test@127.0.0.1:55432/personal_crm_test .venv/bin/python -m personal_crm.simulation

Фактический результат: 28 дней, 28 разных ежедневных digests, 13 возвращённых undated задач, 1 объявление просрочки, 1 вопрос о препятствии, 3 пропуска в одном отчёте, 0 автоматических выполнений, 0 внешних вызовов. Сезонная смена времени включена в управляемые даты. Это симуляция, не четыре недели production-пилота и не измерение p95.

Core demo повторно выполнено после дополнения схемы, все исходные assertions успешны. Обновлённый Compose собран и миграция применена к его сохранённым синтетическим данным. Настоящий HTTP smoke проверяет также plan, overview и history. Legacy: **133 passed in 1.11s**, secret scan прошёл. Изменения по-прежнему только в personal-crm; действующий бот/production не запускались.

После сборки финального исходника выполнен `docker compose ... restart crm-db`; оба HTTP smoke повторно прошли. Проверено сохранение завершённой Telegram-задачи предыдущего smoke в той же отдельной БД. Это restart/persistence, не encrypted backup/restore. Scope и credential-pattern scans проверили все 32 изменённых файла относительно подготовленной ветки; только personal-crm/. `pip check` не обнаружил конфликтов зависимостей.
