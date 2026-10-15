export type Deadline = { precision:'date'|'instant'; value:string; original:string; timezone:string };
export type Task = { id:string; title:string; kind:'task'|'waiting'|'note'; state:'active'|'in_progress'|'deferred'|'done'|'cancelled';
  version:number; deadline:Deadline|null; original_deadline?:Deadline|null; planned_on:string|null; return_on?:string|null;
  reminder_at?:string|null; project_id:string|null; focused:boolean; draft_steps:string[]; overdue?:boolean;
  recurrence_id?:string|null;occurrence_on?:string|null;occurrence_timezone?:string|null;recurrence_warning?:string|null;
  parent_task_id?:string|null;steps_revision?:number;promoted_steps_revision?:number|null };
export type Recurrence = {id:string;version:number;status:'active'|'stopped';frequency:'daily'|'weekly'|'monthly';interval:number;
  anchor_on:string;timezone:string;reminder_time:string|null;template:{title:string}};
export type PlanningSuggestion = {id:string;version:number;kind:'early'|'step'|'reminder_time';task_id:string|null;payload:Record<string,unknown>};
export type Project = {id:string; name:string; description:string; version:number; active_tasks:number};
export type MailEvidenceData = {subject:string;sender:string;excerpt:string;original_at:string|null;direction:string;
  thread_id?:string;attachments_unanalysed:boolean;content_incomplete:boolean};
export type MailStatus = {available:boolean;status:'disabled'|'idle'|'syncing'|'backoff'|'auth_error'|'error';provider:string|null;
  read_only:boolean;window_days:number;poll_seconds:number;last_success_at:string|null;next_sync_at:string|null;
  error_code:string|null;failures:number;saved_count:number;reset_count:number};
export type Proposal = {id:string; version:number; payload:Record<string, unknown>;evidence?:MailEvidenceData|null};
export type Inbox = {proposals:Proposal[]; questions:{id:string;source_version_id:string;text:string;question:string}[];
  errors:{id:string;text:string;error_code:string;retry_at:string|null}[];mail_reviews?:{id:string;evidence:MailEvidenceData}[]};
export type Preferences = { version:number; timezone:string|null; digest_hour:number; initiative_limit:number; catchup_grace_seconds:number;
  ai_paused:boolean;ai_budget_cap_micro_usd:number|null;preferred_reminder_time?:string|null;
  integrations:{telegram_receive:boolean;telegram_send:boolean;mail:boolean;openai:boolean};
  ai:{model:string;configured_budget_usd:string;consent_categories:string[];budget:{spent_micro_usd:number;reserved_micro_usd:number;limit_micro_usd?:number;warning_80?:boolean;blocked?:boolean}} };
export type Overview = {main:Task[];deadlines:Task[];forgotten:Task[];waiting:Task[];proposals:Proposal[];
  guidance:{id:string;message:string}[];other_count:number;sync_errors?:{code:string;message:string}[];planning_suggestions?:PlanningSuggestion[]};
export type Detail = Task & {source:{id:string;text:string;channel:string;received_at:string};
  history:{id:string;reason:string;task_version:number;created_at:string;after:Task}[];recurrence?:Recurrence|null;children?:Task[];
  legacy_import?:{reminder_at:string|null;repeat_rule:string|null}|null};
export type Page = {items:Task[];total:number;offset:number;limit:number};

const messages:Record<string,string> = {
  unauthorized:'Ключ доступа не подошёл. Введите ключ владельца.', owner_not_configured:'Настройте владельца и ключ доступа на сервере.',
  recovery_hold:'База восстановлена и ожидает проверки. Отправки заблокированы; завершите проверку восстановления на сервере.',
  web_auth_not_configured:'Настройте пароль и адрес веб-приложения на сервере.',
  csrf_forbidden:'Сессия изменилась. Обновите страницу и повторите действие.',
  login_rate_limited:'Слишком много попыток входа. Подождите 15 минут.',
  database_unavailable:'База данных временно недоступна. Повторите попытку позже.', version_conflict:'Дело уже изменилось. Обновите карточку и проверьте правку.',
  proposal_conflict:'Предложение уже обработано или изменилось. Обновите входящие.', task_inactive:'Это дело уже завершено или отменено.',
  ambiguous_or_invalid_time:'Проверьте дату и время. При переводе часов выберите однозначное время.',
  profile_timezone_required:'Сначала задайте часовой пояс в настройках.', invalid_timezone:'Укажите существующий часовой пояс, например Europe/Moscow.',
  source_revision_conflict:'Этот запрос уже сохранён с другими значениями. Обновите форму.',
  server_unavailable:'Сервер временно недоступен. Повторите попытку; результат сохранения пока неизвестен.',
  response_unreadable:'Ответ сервера не удалось прочитать. Повторите попытку; результат сохранения пока неизвестен.',
  ai_disabled:'Разбор с помощью ИИ выключен. Исходное сообщение сохранено.',
  ai_previous_attempt:'Результат предыдущего платного запроса неопределён. Автоматический повтор остановлен.',
  ai_rate_limit:'Провайдер ограничил запросы. Назначен ограниченный повтор.',
  budget_exceeds_server_limit:'Пользовательский лимит не может превышать разрешённый лимит сервера.',
  mail_disabled:'Чтение почты выключено. Подключение требует отдельной настройки и разрешения владельца.',
  mail_configuration_invalid:'Проверьте серверную настройку IMAP и точное имя папки отправленных.',
  mail_account_mismatch:'Настроен другой ящик. Переключение требует отдельной процедуры; прежние данные сохранены.',
  recurrence_already_exists:'У этого дела уже есть правило повторения. Измените существующее правило.',
  recurrence_out_of_range:'Расписание выходит за допустимые границы календаря.',
  recurrence_has_no_open_task:'В этой серии нет открытого экземпляра. Создайте новое дело для продолжения.',
  step_plan_required:'Сначала сохраните непустой черновик шагов для активного дела.',
};
export class ApiError extends Error { constructor(public status:number, public code:string) {super(messages[code] || 'Не удалось сохранить изменение. Проверьте значения и повторите попытку.');} }
function requester(authHeaders:Record<string,string>,expired?:()=>void) {
  return async function request<T>(path:string, method='GET', body?:unknown, signal?:AbortSignal):Promise<T> {
    if(!path.startsWith('/')||path.startsWith('//'))throw new Error('Недопустимый адрес запроса.');
    let response:Response;
    try { response = await fetch(path,{method,signal,credentials:'same-origin',headers:{...authHeaders,...(body ? {'Content-Type':'application/json'} : {})},...(body ? {body:JSON.stringify(body)} : {})}); }
    catch(error) { if ((error as Error).name === 'AbortError') throw error; throw new Error('Нет связи с сервером. Проверьте подключение; результат сохранения пока неизвестен.'); }
    if(response.status===401)expired?.();
    let data:unknown;
    try {data=await response.json();}
    catch(error) {
      if((error as Error).name==='AbortError')throw error;
      throw new ApiError(response.status,response.status===401?'unauthorized':response.status>=500?'server_unavailable':'response_unreadable');
    }
    if (!response.ok) {
      const detail=data&&typeof data==='object'&&'detail' in data?data.detail:undefined;
      throw new ApiError(response.status,typeof detail==='string'?detail:response.status>=500?'server_unavailable':'invalid_input');
    }
    return data as T;
  };
}
export function makeApi(token:string) {return requester({Authorization:`Bearer ${token}`});}
export function makeSessionApi(csrf:string,expired?:()=>void) {return requester({'X-CSRF-Token':csrf},expired);}
export type Session={authenticated:boolean;csrf_token:string};
export function loadSession(){return requester({})<Session>('/auth/session');}
export function loginSession(password:string){return requester({})<Session>('/auth/login','POST',{password});}
export type Api = ReturnType<typeof makeApi>;
export const stateLabels:Record<Task['state'],string> = {active:'Активно',in_progress:'В работе',deferred:'Отложено',done:'Выполнено',cancelled:'Отменено'};
export const kindLabels = {task:'Задача',waiting:'Ожидание',note:'Заметка'};
export function localInput(value:string|null|undefined,zone:string|null):string {
  if(!value) return '';
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:zone || 'UTC',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
  const get=(name:string)=>parts.find(p=>p.type===name)?.value;
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}
export function displayDate(value:string,zone:string|null,instant=false):string {
  return new Intl.DateTimeFormat('ru-RU',{timeZone:instant ? zone || 'UTC' : 'UTC',dateStyle:'medium',...(instant ? {timeStyle:'short'} : {})}).format(new Date(instant ? value : `${value}T12:00:00Z`));
}
