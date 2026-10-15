import { useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react';
import { displayDate, kindLabels, localInput, stateLabels, type Api, type Detail, type Preferences, type Project, type Task } from './api';
import { useLoad } from './hooks';
import { TaskPlanning } from './planning';
import { LegacyNotice } from './data-tools';

export function Notice({error,children}:{error?:boolean;children:ReactNode}) {return <div className={error?'notice error':'notice'} role={error?'alert':undefined}>{children}</div>;}
export function Empty({title,children}:{title:string;children?:ReactNode}) {return <div className="empty"><span className="empty-mark" aria-hidden="true">○</span><h3>{title}</h3>{children?<p>{children}</p>:null}</div>;}
export function Dialog({title,close,children}:{title:string;close:()=>void;children:ReactNode}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const dialog=ref.current;dialog?.showModal();return ()=>{dialog?.close();document.getElementById('page-title')?.focus();};},[]);
  return <dialog ref={ref} className="dialog" aria-label={title} onCancel={close}><header className="dialog-head"><h2>{title}</h2><button className="icon-button" aria-label="Закрыть окно" onClick={close}>×</button></header>{children}</dialog>;
}
export function TaskRows({tasks,zone,open}:{tasks:Task[];zone:string|null;open:(id:string)=>void}) {
  return <div className="task-list">{tasks.map(task=><article className="task-row" key={task.id}>
    <span className={`task-marker ${task.state}`} aria-hidden="true">{task.state==='done'?'✓':task.focused?'•':''}</span>
    <div className="task-copy"><button className="task-title" onClick={()=>open(task.id)}>{task.title}</button><div className="task-meta">
      <span className={`state ${task.state}`}>{stateLabels[task.state]}</span>{task.kind!=='task'?<span>{kindLabels[task.kind]}</span>:null}
      {task.deadline?<span className={task.overdue?'late':''}>{task.overdue?'Просрочено: ':'Срок: '}{displayDate(task.deadline.value,task.deadline.timezone,task.deadline.precision==='instant')}</span>:null}
      {task.planned_on?<span>План: {displayDate(task.planned_on,zone)}</span>:null}
      {task.recurrence_id?<span>↻ Повторение{task.occurrence_on?` · ${displayDate(task.occurrence_on,task.occurrence_timezone || zone)}`:''}</span>:null}
      {task.parent_task_id?<span>Шаг плана</span>:null}
      {task.reminder_at?<span>Напомнить: {displayDate(task.reminder_at,zone,true)}</span>:null}
    </div></div><button className="icon-button row-open" aria-label={`Открыть ${task.title}`} onClick={()=>open(task.id)}>↗</button>
  </article>)}</div>;
}

export function TaskForm({task,projects,zone,onSave}:{task?:Task;projects:Project[];zone:string|null;onSave:(values:Record<string,unknown>)=>Promise<void>}) {
  const initialDeadline=task?.deadline ? task.deadline.precision==='date'?task.deadline.value:localInput(task.deadline.value,task.deadline.timezone):'';
  const initialReminder=localInput(task?.reminder_at,zone);
  const [title,setTitle]=useState(task?.title || '');
  const [kind,setKind]=useState(task?.kind || 'task');
  const [project,setProject]=useState(task?.project_id || '');
  const [plan,setPlan]=useState(task?.planned_on || '');
  const [deadline,setDeadline]=useState(initialDeadline);
  const [precision,setPrecision]=useState(task?.deadline?.precision || 'date');
  const [reminder,setReminder]=useState(initialReminder);
  const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  const requestId=useRef(crypto.randomUUID());
  function change(fn:()=>void) {requestId.current=crypto.randomUUID();fn();}
  const dirty=!task || title!==task.title || project!==(task.project_id || '') || plan!==(task.planned_on || '') || deadline!==initialDeadline || reminder!==initialReminder;
  async function submit(event:FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    const values:Record<string,unknown>=task ? {version:task.version} : {request_id:requestId.current,title:title.trim(),kind};
    if(!task || title!==task.title) values.title=title.trim();
    if(!task || project!==(task.project_id || '')) values.project_id=project || null;
    if(!task || plan!==(task.planned_on || '')) values.planned_on=plan || null;
    if(!task || deadline!==initialDeadline) values.deadline_local=deadline || null;
    if(!task || reminder!==initialReminder) values.reminder_local=reminder || null;
    try {await onSave(values);} catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <form className="task-form" onSubmit={submit}><fieldset disabled={busy}>
    <label>Название<input autoFocus required maxLength={2000} value={title} onChange={e=>change(()=>setTitle(e.target.value))}/></label>
    <div className="form-grid"><label>Тип<select value={kind} disabled={!!task} onChange={e=>change(()=>setKind(e.target.value as Task['kind']))}><option value="task">Задача</option><option value="waiting">Ожидание ответа</option><option value="note">Заметка</option></select></label>
    <label>Проект<select value={project} onChange={e=>change(()=>setProject(e.target.value))}><option value="">Без проекта</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div>
    <div className="calendar-fields"><label>День выполнения<input type="date" value={plan} onChange={e=>change(()=>setPlan(e.target.value))}/><small>Когда вы планируете заняться делом.</small></label>
      <div><label>Точность дедлайна<select value={precision} onChange={e=>change(()=>{setPrecision(e.target.value as 'date'|'instant');setDeadline('');})}><option value="date">Календарная дата</option><option value="instant">Дата и точное время</option></select></label>
      <label>Дедлайн<input type={precision==='date'?'date':'datetime-local'} value={deadline} onChange={e=>change(()=>setDeadline(e.target.value))}/><small>Крайний срок обязательства.</small></label></div>
      <label>Напомнить в<input type="datetime-local" value={reminder} onChange={e=>change(()=>setReminder(e.target.value))}/><small>Отдельное уведомление · {zone || 'сначала задайте часовой пояс'}.</small></label>
    </div>
    {error?<Notice error>{error}</Notice>:null}
    <button className="primary" type="submit" disabled={!dirty || busy}>{busy?'Сохраняем…':task?'Сохранить изменения':'Сохранить дело'}</button>
  </fieldset></form>;
}

export function TaskDialog({id,api,revision,preferences,projects,close,changed,open}:{id:string;api:Api;revision:number;preferences:Preferences;projects:Project[];close:()=>void;changed:(message:string)=>void;open?:(id:string)=>void}) {
  const [localRevision,setLocalRevision]=useState(0); const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [returnOn,setReturnOn]=useState('');
  const load=useLoad<Detail>(api,`/workspace/tasks/${id}`,revision+localRevision);
  async function command(action:string,extra:Record<string,unknown>={}) {
    if(!load.data)return;setBusy(true);setError('');
    try {await api(`/tasks/${id}/commands`,'POST',{version:load.data.version,action,...extra}); changed(action==='close'?'Дело выполнено':'Изменение сохранено');close();}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const task=load.data;
  return <Dialog title="Карточка дела" close={close}>{load.error?<Notice error>{load.error}</Notice>:null}{load.loading?<p className="loading">Загружаем дело…</p>:task?<>
    <div className="detail-state"><span className={`state ${task.state}`}>{stateLabels[task.state]}</span><span>Версия {task.version}</span><button className="text-button" onClick={()=>setLocalRevision(v=>v+1)}>Обновить карточку</button></div>
    {task.state==='done' || task.state==='cancelled'?<h3 className="done-title">{task.title}</h3>:<TaskForm key={`${task.id}:${task.version}`} task={task} projects={projects} zone={preferences.timezone} onSave={async values=>{await api(`/workspace/tasks/${id}`,'PATCH',values);changed('Изменения сохранены');close();}}/>}
    {task.state!=='done' && task.state!=='cancelled'?<div className="task-actions"><button className="success-button" disabled={busy} onClick={()=>command('close')}>{task.recurrence_id?'Выполнить экземпляр':'Выполнить дело'}</button>
      <button disabled={busy} onClick={()=>command(task.state==='in_progress'?'activate':task.state==='deferred'?'resume':'start')}>{task.state==='in_progress'?'Вернуть в активные':task.state==='deferred'?'Вернуть сейчас':'Начать работу'}</button>
      <button disabled={busy} onClick={()=>command('focus',{focused:!task.focused})}>{task.focused?'Убрать из фокуса':'В фокус'}</button>
      <label>Вернуться к делу<input type="date" value={returnOn} onChange={e=>setReturnOn(e.target.value)}/></label><button disabled={busy || !returnOn} onClick={()=>command('defer',{return_on:returnOn})}>Отложить</button>
      <button className="danger-button" disabled={busy} onClick={()=>{if(window.confirm(task.recurrence_id?'Отменить только этот экземпляр? Повторение сохранится.':'Отменить это дело?')) void command('cancel');}}>{task.recurrence_id?'Отменить экземпляр':'Отменить дело'}</button></div>:null}
    {error?<Notice error>{error}</Notice>:null}
    {task.original_deadline?<p className="muted">Первоначальный срок: {displayDate(task.original_deadline.value,task.original_deadline.timezone,task.original_deadline.precision==='instant')}</p>:null}
    {task.legacy_import?<LegacyNotice legacy={task.legacy_import} zone={preferences.timezone}/>:null}
    <TaskPlanning key={`${task.id}:${task.version}`} task={task} api={api} zone={preferences.timezone} preferredTime={preferences.preferred_reminder_time || null} changed={changed} open={open}/>
    <details className="detail-section"><summary>Источник</summary><p className="source-text">{task.source.text}</p><small>{task.source.channel==='mail'?'Почта':task.source.channel==='forward'?'Пересылка':'Ввод владельца'} · {displayDate(task.source.received_at,preferences.timezone,true)}</small></details>
    <details className="detail-section"><summary>История изменений · {task.history.length}</summary><ol className="history">{task.history.map(h=><li key={h.id}><time>{displayDate(h.created_at,preferences.timezone,true)}</time><span>Версия {h.task_version} · {stateLabels[h.after.state]}</span><strong>{h.after.title}</strong></li>)}</ol></details>
  </>:null}</Dialog>;
}
