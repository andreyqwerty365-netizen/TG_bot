import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, displayDate, stateLabels, type Api, type Inbox, type Overview, type Page, type Preferences, type Project } from './api';
import { useLoad } from './hooks';
import { Dialog, Empty, Notice, TaskRows } from './components';
import { MailEvidence, MailPanel, MailReview } from './mail';
import { PlanningBoard } from './planning';
import { DataPanel } from './data-tools';
import { QuickCapture } from './capture';
import { OperationsPanel } from './operations';

export type ScreenProps={api:Api;preferences:Preferences;projects:Project[];revision:number;open:(id:string)=>void;changed:(message:string)=>void};

export function Today(props:ScreenProps) {
  const [retry,setRetry]=useState(0);
  const load=useLoad<Overview>(props.api,'/overview',props.revision+retry);const view=load.data;
  return <div className="today-layout"><div className="today-main">
    <QuickCapture api={props.api} changed={props.changed} open={props.open}/>
    {load.error?<Notice error>{load.error}<button onClick={()=>setRetry(v=>v+1)}>Повторить загрузку обзора</button></Notice>:
    load.loading?<p className="loading">Собираем актуальный обзор…</p>:view?<>
    {view.sync_errors?.map(item=><Notice error key={item.code}>{item.message}</Notice>)}
    {view.proposals.length?<section className="panel"><span className="eyebrow">Ваше решение</span><h2>На подтверждение: {view.proposals.length}</h2><p>Предложения ещё не изменили ваши дела.</p><a href="#inbox">Открыть входящие →</a></section>:null}
    <section className="panel focus-panel"><header className="section-heading"><div><span className="eyebrow">Сначала главное</span><h2>До трёх дел в фокусе</h2></div><span className="count">{view.main.length}</span></header>
      {view.main.length?<TaskRows tasks={view.main} zone={props.preferences.timezone} open={props.open}/>:<Empty title="Можно начать с одного дела">Добавьте задачу, которой хотите заняться сегодня.</Empty>}
      <footer className="panel-footer">{view.other_count?`Ещё ${view.other_count} дел — в полном списке.`:'Вы можете выбрать фокус в карточке любого дела.'}</footer>
    </section>
    <PlanningBoard items={view.planning_suggestions || []} api={props.api} changed={props.changed} zone={props.preferences.timezone}/>
    {view.guidance.length?<section className="panel"><h2>Разобраться с препятствием</h2>{view.guidance.map(g=><p className="guidance" key={g.id}>{g.message}</p>)}</section>:null}
    <section className="panel"><header className="section-heading"><div><span className="eyebrow">Без спешки</span><h2>Вернуться к забытым делам</h2></div></header>
      {view.forgotten.length?<TaskRows tasks={view.forgotten} zone={props.preferences.timezone} open={props.open}/>:<Empty title="Ничего не потерялось">Дела без срока будут возвращаться сюда по мере необходимости.</Empty>}
    </section></>:null}</div>
    {!load.loading&&!load.error&&view?<aside className="today-side"><section className="panel"><header className="section-heading"><h2>Сроки и просрочки</h2><span className="count">{view.deadlines.length}</span></header>
      {view.deadlines.length?<TaskRows tasks={view.deadlines} zone={props.preferences.timezone} open={props.open}/>:<Empty title="Сроков пока нет">Дедлайн можно добавить отдельно от плана выполнения.</Empty>}
    </section><section className="panel"><h2>Ожидаете ответ</h2>{view.waiting.length?<TaskRows tasks={view.waiting} zone={props.preferences.timezone} open={props.open}/>:<p className="muted">Нет открытых ожиданий.</p>}</section>
    <div className="quiet-note"><span aria-hidden="true">↳</span><p>Обзор помогает выбрать следующий шаг. Решения о сроках и выполнении остаются за вами.</p></div></aside>:null}</div>;
}

export function AllTasks(props:ScreenProps & {initialProject?:string}) {
  const [query,setQuery]=useState('');const [debounced,setDebounced]=useState('');const [state,setState]=useState('');const [kind,setKind]=useState('');
  const [project,setProject]=useState(props.initialProject || '');const [channel,setChannel]=useState('');const [deadline,setDeadline]=useState('');const [offset,setOffset]=useState(0);
  useEffect(()=>{const timer=setTimeout(()=>setDebounced(query),250);return ()=>clearTimeout(timer);},[query]);
  const params=new URLSearchParams({q:debounced,offset:String(offset),limit:'30'});
  if(state)params.set('state',state);if(kind)params.set('kind',kind);if(project)params.set('project_id',project);if(channel)params.set('channel',channel);if(deadline)params.set('deadline',deadline);
  const load=useLoad<Page>(props.api,'/workspace/tasks?'+params,props.revision);
  const change=(action:()=>void)=>{setOffset(0);action();};
  return <><div className="filter-panel"><label className="search-box"><span aria-hidden="true">⌕</span><span className="sr-only">Найти дело</span><input aria-label="Найти дело" type="search" placeholder="Найти дело по названию" value={query} onChange={e=>change(()=>setQuery(e.target.value))}/></label>
    <div className="filters"><label><span className="sr-only">Состояние</span><select value={state} onChange={e=>change(()=>setState(e.target.value))}><option value="">Все состояния</option>{Object.entries(stateLabels).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label>
    <label><span className="sr-only">Тип дела</span><select value={kind} onChange={e=>change(()=>setKind(e.target.value))}><option value="">Все типы</option><option value="task">Задачи</option><option value="waiting">Ожидания</option><option value="note">Заметки</option></select></label>
    <label><span className="sr-only">Фильтр по проекту</span><select value={project} onChange={e=>change(()=>setProject(e.target.value))}><option value="">Все проекты</option>{props.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <label><span className="sr-only">Источник дела</span><select value={channel} onChange={e=>change(()=>setChannel(e.target.value))}><option value="">Все источники</option><option value="owner">Мой ввод</option><option value="forward">Пересылки</option><option value="mail">Почта</option></select></label>
    <label><span className="sr-only">Фильтр сроков</span><select value={deadline} onChange={e=>change(()=>setDeadline(e.target.value))}><option value="">Все сроки</option><option value="overdue">Просроченные</option><option value="upcoming">Предстоящие сроки</option><option value="none">Без дедлайна</option></select></label></div></div>
    {load.error?<Notice error>{load.error}</Notice>:load.loading || query!==debounced?<p className="loading">Ищем в сохранённых делах…</p>:<section className="panel all-panel"><header className="section-heading"><h2>Дела <span className="muted">· {load.data?.total || 0}</span></h2></header>
      {load.data?.items.length?<TaskRows tasks={load.data.items} zone={props.preferences.timezone} open={props.open}/>:<Empty title="Таких дел пока нет">Измените поиск или добавьте новое дело.</Empty>}
      {load.data && load.data.total>30?<div className="pagination"><button disabled={offset===0} onClick={()=>setOffset(o=>Math.max(0,o-30))}>Назад</button><span>{offset+1}–{Math.min(offset+30,load.data.total)} из {load.data.total}</span><button disabled={offset+30>=load.data.total} onClick={()=>setOffset(o=>o+30)}>Дальше</button></div>:null}
    </section>}</>;
}

function QuestionReply({question,api,changed}:{question:Inbox['questions'][number];api:Api;changed:(message:string)=>void}) {
  const [text,setText]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const request=useRef(crypto.randomUUID());
  return <article className="inbox-item"><span className="eyebrow">Нужно уточнение</span><h3>{question.question}</h3><p className="source-text">{question.text}</p>
    <form className="inline-form" onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try {
      const result=await api<{status:string;question?:string}>(`/workspace/sources/${question.source_version_id}/reply`,'POST',{request_id:request.current,text});
      changed(result.status==='created'?'Дело сохранено':result.status==='changed'?'Изменение сохранено':result.status==='error'?'Сообщение сохранено. Разбор не завершён.':'Уточнение сохранено');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>
    <label><span className="sr-only">Ответ на уточнение</span><input required value={text} disabled={busy} placeholder="Например: в 19:00" onChange={e=>{request.current=crypto.randomUUID();setText(e.target.value);}}/></label><button className="primary" disabled={busy}>{busy?'Сохраняем…':'Ответить'}</button></form>{error?<Notice error>{error}</Notice>:null}</article>;
}

export function Incoming(props:ScreenProps) {
  const load=useLoad<Inbox>(props.api,'/workspace/inbox',props.revision);const [busy,setBusy]=useState('');const [error,setError]=useState('');
  async function confirm(id:string,version:number,accept:boolean) {setBusy(id);setError('');try{await props.api(`/proposals/${id}/confirm`,'POST',{version,accept});props.changed(accept?'Предложение принято':'Предложение отклонено');}catch(e){setError((e as Error).message);}finally{setBusy('');}}
  if(load.error)return <Notice error>{load.error}</Notice>;if(load.loading)return <p className="loading">Загружаем входящие…</p>;const data=load.data!;
  return <><p className="section-intro">Предложения становятся делами после вашего решения. Сохранённые сообщения можно уточнить или повторно разобрать.</p>{error?<Notice error>{error}</Notice>:null}
    <section className="panel inbox-panel">{!data.proposals.length&&!data.questions.length&&!data.errors.length&&!data.mail_reviews?.length?<Empty title="Входящие разобраны">Здесь появятся предложения, уточнения и сообщения с незавершённым разбором.</Empty>:null}
    {data.proposals.map(p=><article className="inbox-item" key={p.id}><span className="eyebrow">Предложение</span><h3>{String(p.payload.title || 'Изменение существующего дела')}</h3>
      <p>{{close:'Отметить дело выполненным',reminder:'Изменить время напоминания',deadline:'Изменить дедлайн',title:'Изменить название',edit:'Изменить название и напоминание',plan:'Изменить день выполнения',defer:'Отложить дело',cancel:'Отменить дело',steps:'Обновить черновик шагов'}[String(p.payload.change)] || 'Создать новое дело'}</p>
      {Array.isArray(p.payload.draft_steps)&&p.payload.draft_steps.length?<ol>{p.payload.draft_steps.map((step,i)=><li key={i}>{String(step)}</li>)}</ol>:null}
      {p.payload.reminder_at?<p>Напомнить: {displayDate(String(p.payload.reminder_at),props.preferences.timezone,true)}</p>:null}
      {p.payload.deadline?<p>Срок: {String((p.payload.deadline as {value:string}).value)}</p>:null}
      {p.payload.planned_on?<p>План: {displayDate(String(p.payload.planned_on),props.preferences.timezone)}</p>:null}
      {p.evidence?<MailEvidence evidence={p.evidence} zone={props.preferences.timezone}/>:null}
      <div className="button-row"><button className="primary" disabled={!!busy} onClick={()=>confirm(p.id,p.version,true)}>Принять</button><button disabled={!!busy} onClick={()=>confirm(p.id,p.version,false)}>Отклонить</button></div></article>)}
    {data.mail_reviews?.map(item=><MailReview key={item.id} {...item} api={props.api} zone={props.preferences.timezone} changed={props.changed}/>)}
    {data.questions.map(q=><QuestionReply key={q.id} question={q} api={props.api} changed={props.changed}/>)}
    {data.errors.map(item=><article className="inbox-item" key={item.id}><span className="eyebrow">Сообщение сохранено</span><h3>Разбор не завершён</h3><p className="source-text">{item.text}</p>
      <p className="muted">{item.retry_at?'Назначена ограниченная повторная обработка.':item.error_code==='ai_disabled'?'ИИ выключен. Используйте ручное создание дела или включите разрешённую обработку в конфигурации.':['ai_timeout','ai_previous_attempt'].includes(item.error_code)?'Платный запрос мог быть выполнен. Повтор остановлен до проверки расходов.':'Источник сохранён. После исправления причины можно повторить обработку.'}</p>
      <button disabled={!!busy || ['ai_timeout','ai_previous_attempt'].includes(item.error_code)} onClick={async()=>{setBusy(item.id);setError('');try{const result=await props.api<{status:string}>(`/sources/${item.id}/retry`,'POST');props.changed(result.status==='created'?'Дело сохранено':result.status==='error'?'Источник сохранён; разбор пока не завершён':'Разбор выполнен');}catch(e){setError((e as Error).message);}finally{setBusy('');}}}>Повторить разбор</button></article>)}
    </section></>;
}

export function Projects(props:ScreenProps & {showTasks:(id:string)=>void}) {
  const [editing,setEditing]=useState<Project|'new'|null>(null);const [name,setName]=useState('');const [description,setDescription]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  function edit(item:Project|'new'){setEditing(item);setName(item==='new'?'':item.name);setDescription(item==='new'?'':item.description);setError('');}
  return <><div className="section-toolbar"><p className="section-intro">Объединяйте связанные дела и держите контекст рядом.</p><button className="primary" onClick={()=>edit('new')}>Создать проект</button></div>
    {props.projects.length?<div className="project-grid">{props.projects.map(p=><article className="panel project-card" key={p.id}><span className="project-icon" aria-hidden="true">▱</span><button className="project-title" onClick={()=>props.showTasks(p.id)}>{p.name}</button><p>{p.description || 'Добавьте описание, чтобы сохранить контекст проекта.'}</p><footer><span>{p.active_tasks} незавершённых дел</span><button className="text-button" onClick={()=>edit(p)}>Изменить</button></footer></article>)}</div>:<section className="panel"><Empty title="Первый проект начинается с идеи">Создайте проект и добавьте в него дела из карточки задачи.</Empty></section>}
    {editing?<Dialog title={editing==='new'?'Новый проект':'Изменить проект'} close={()=>setEditing(null)}><form className="task-form" onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await props.api(editing==='new'?'/workspace/projects':`/workspace/projects/${editing.id}`,editing==='new'?'POST':'PATCH',{name,description,...(editing==='new'?{}:{version:editing.version})});props.changed('Проект сохранён');setEditing(null);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>
      <fieldset disabled={busy}><label>Название проекта<input required autoFocus maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></label><label>Описание<textarea maxLength={4000} value={description} onChange={e=>setDescription(e.target.value)}/></label>{error?<Notice error>{error}</Notice>:null}<button className="primary">{busy?'Сохраняем…':'Сохранить проект'}</button></fieldset></form></Dialog>:null}
  </>;
}

export function SettingsScreen(props:ScreenProps) {
  const prefs=props.preferences;const [timezone,setTimezone]=useState(prefs.timezone || '');const [hour,setHour]=useState(prefs.digest_hour);const [limit,setLimit]=useState(prefs.initiative_limit);const [grace,setGrace]=useState(Math.round(prefs.catchup_grace_seconds/60));const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const budget=prefs.ai.budget;
  const initialCap=prefs.ai_budget_cap_micro_usd==null?'':String(prefs.ai_budget_cap_micro_usd/1e6);
  const [paused,setPaused]=useState(prefs.ai_paused || false);const [cap,setCap]=useState(initialCap);
  const [preferredTime,setPreferredTime]=useState(prefs.preferred_reminder_time || '');
  async function save(e:FormEvent) {e.preventDefault();setBusy(true);setError('');try{await props.api('/workspace/settings','PATCH',{version:prefs.version,timezone,digest_hour:hour,initiative_limit:limit,catchup_grace_seconds:grace*60,ai_paused:paused,
    preferred_reminder_time:preferredTime || null,...(cap!==initialCap?{ai_budget_cap_micro_usd:cap===''?null:Math.round(Number(cap)*1e6)}:{})});props.changed('Настройки сохранены');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <div className="settings-layout"><section className="panel"><h2>Ваш ритм</h2><form className="task-form" onSubmit={save}><fieldset disabled={busy}>
    <label>Часовой пояс<input required list="timezones" value={timezone} onChange={e=>setTimezone(e.target.value)}/><datalist id="timezones"><option>Europe/Moscow</option><option>Europe/Berlin</option><option>Asia/Yekaterinburg</option><option>Asia/Novosibirsk</option><option>UTC</option></datalist><small>Пояс указан явно. При его изменении уже назначенные точные уведомления сохраняют свой момент.</small></label>
    <label>Час ежедневной сводки<input type="number" min={0} max={23} required value={hour} onChange={e=>setHour(Number(e.target.value))}/></label>
    <label>Предпочтительное время новых напоминаний<input type="time" value={preferredTime} onChange={e=>setPreferredTime(e.target.value)}/><small>Предлагается для проверки в форме повторений. Уже назначенные уведомления не перемещаются. Пустое поле не задаёт время.</small></label>
    <label>Дополнительные напоминания в сутки<select value={limit} onChange={e=>setLimit(Number(e.target.value))}><option value={0}>0 — только точные уведомления и сводка</option><option value={1}>Не больше одного</option><option value={2}>Не больше двух</option></select><small>Ваши точные напоминания не расходуют этот лимит. Автоматический повтор расходует.</small></label>
    <label>Допустимое опоздание после простоя, минут<input type="number" min={1} max={1440} required value={grace} onChange={e=>setGrace(Number(e.target.value))}/></label>
    <label className="checkbox-label"><input type="checkbox" checked={paused} onChange={e=>setPaused(e.target.checked)}/>Приостановить разбор с ИИ</label>
    <label>Мой месячный лимит ИИ, USD<input type="number" min={0} step="0.000001" max={Number(prefs.ai.configured_budget_usd)} value={cap} placeholder={prefs.ai.configured_budget_usd} onChange={e=>setCap(e.target.value)}/><small>Можно уменьшить разрешённый лимит. Ноль блокирует новые платные вызовы; пустое поле использует серверный предел. Уже уменьшенный лимит текущего месяца автоматически не повышается.</small></label>
    {error?<Notice error>{error}</Notice>:null}<button className="primary">{busy?'Сохраняем…':'Сохранить настройки'}</button></fieldset></form></section>
    <aside><section className="panel"><h2>Подключения</h2><dl className="connection-list"><dt>Telegram · приём</dt><dd>{prefs.integrations.telegram_receive?'Включён в конфигурации':'Выключен'}</dd><dt>Telegram · доставка</dt><dd>{prefs.integrations.telegram_send?'Включена в конфигурации':'Выключена'}</dd><dt>OpenAI</dt><dd>{prefs.integrations.openai?'Включён в конфигурации':'Выключен'}</dd></dl><p className="muted">Реальные аккаунты подключаются отдельной серверной настройкой. Ключи интеграций остаются на сервере.</p></section>
    <MailPanel api={props.api} revision={props.revision} changed={props.changed} zone={prefs.timezone}/>
    <OperationsPanel api={props.api} revision={props.revision} zone={prefs.timezone}/>
    <DataPanel api={props.api}/>
    <section className="panel budget-panel"><span className="eyebrow">Контроль расходов</span><h2>Бюджет ИИ</h2><div className="budget-value">${(budget.spent_micro_usd/1e6).toFixed(4)}<small>учтённые расходы за месяц</small></div><p>Резерв: ${(budget.reserved_micro_usd/1e6).toFixed(4)}</p><p>Лимит: ${budget.limit_micro_usd!==undefined?(budget.limit_micro_usd/1e6).toFixed(4):prefs.ai.configured_budget_usd}</p>
      {budget.blocked?<Notice error>Новые платные обращения остановлены лимитом.</Notice>:budget.warning_80?<Notice>Использовано или зарезервировано не меньше 80% лимита.</Notice>:null}
      <p className="muted">{prefs.ai_paused?'Разбор приостановлен владельцем. ':''}{prefs.ai.model?`Модель: ${prefs.ai.model}`:'Модель ещё не выбрана.'} Верхний предел, разрешённая модель и категории передачи задаются серверной конфигурацией.</p>
      <p className="muted">Категории согласия: {prefs.ai.consent_categories.length?prefs.ai.consent_categories.join(', '):'передача данных не разрешена'}.</p></section></aside></div>;
}
