import { useRef, useState, type FormEvent } from 'react';
import { displayDate, stateLabels, type Api, type Detail, type PlanningSuggestion } from './api';
import { Notice } from './components';

export function PlanningBoard({items,api,changed,zone}:{items:PlanningSuggestion[];api:Api;changed:(message:string)=>void;zone:string|null}) {
  const [busy,setBusy]=useState('');const [error,setError]=useState('');
  async function decide(item:PlanningSuggestion,accept:boolean){setBusy(item.id);setError('');try{
    await api(`/workspace/suggestions/${item.id}/confirm`,'POST',{version:item.version,accept});
    changed(accept?'Предложение применено':'Предложение скрыто');
  }catch(e){setError((e as Error).message);}finally{setBusy('');}}
  return <section className="panel planning-board"><header className="section-heading"><div><span className="eyebrow">Следующий шаг</span><h2>Можно сделать проще</h2></div></header>
    <p className="muted">Предложения меняют план, состояние или предпочтения только после вашего решения.</p>
    {items.slice(0,8).map(item=><article className="planning-card" key={item.id}><span className="planning-label">{item.kind==='early'?'Закончить раньше':item.kind==='step'?'Небольшой старт':'Предпочтительное время'}</span>
      <h3>{String(item.payload.title || 'Время для будущих форм')}</h3>
      {item.kind==='early'?<p>Запланировать на {displayDate(String(item.payload.planned_on),zone)}. Внешний срок остаётся {String((item.payload.deadline as {value:string}).value)}.</p>:
       item.kind==='step'?<><p>{String(item.payload.step)}</p>{item.payload.generic?<small>Общий приём для старта. Конкретные шаги можно записать в карточке дела.</small>:null}</>:
       <p>Вы явно выбирали {String(item.payload.reminder_time)} для {Number(item.payload.explicit_choices)} разных дел. Использовать это время как предложение в новых формах? Уже назначенные уведомления сохранят свои моменты.</p>}
      <div className="button-row"><button className="primary" disabled={!!busy} onClick={()=>decide(item,true)}>{item.kind==='early'?'Принять план':item.kind==='step'?'Начать с шага':'Использовать в будущих формах'}</button><button disabled={!!busy} onClick={()=>decide(item,false)}>Скрыть предложение</button></div>
    </article>)}
    {items.length>8?<p className="muted">Ещё предложений: {items.length-8}. Разберите видимые, чтобы перейти к остальным.</p>:null}
    {!items.length?<p>Подготовьте варианты по текущим делам и срокам. Они не создадут задач или уведомлений автоматически.</p>:null}
    <button className="text-button" disabled={!!busy} onClick={async()=>{setBusy('refresh');setError('');try{await api('/workspace/suggestions/refresh','POST');changed('Предложения обновлены');}catch(e){setError((e as Error).message);}finally{setBusy('');}}}>Подготовить предложения</button>
    {error?<Notice error>{error}</Notice>:null}
  </section>;
}

export function TaskPlanning({task,api,zone,preferredTime,changed,open}:{task:Detail;api:Api;zone:string|null;preferredTime:string|null;changed:(message:string)=>void;open?:(id:string)=>void}) {
  const rule=task.recurrence;const active=!['done','cancelled'].includes(task.state);
  const [steps,setSteps]=useState(task.draft_steps.join('\n'));const [busy,setBusy]=useState('');const [error,setError]=useState('');
  const [frequency,setFrequency]=useState(rule?.frequency || 'daily');const [interval,setInterval]=useState(rule?.interval || 1);
  const [anchor,setAnchor]=useState(task.occurrence_on || task.planned_on || '');
  const [wall,setWall]=useState(rule?.reminder_time || preferredTime || '');const [remind,setRemind]=useState(!!rule?.reminder_time);
  const [seriesTitle,setSeriesTitle]=useState(rule?.template.title || task.title);
  const request=useRef(crypto.randomUUID());
  const promoted=task.promoted_steps_revision!=null&&task.promoted_steps_revision===task.steps_revision;
  async function run(key:string,call:()=>Promise<unknown>,message:string){setBusy(key);setError('');try{await call();changed(message);}catch(e){setError((e as Error).message);}finally{setBusy('');}}
  async function saveRule(e:FormEvent){e.preventDefault();await run('rule',()=>rule?
    api(`/workspace/recurrences/${rule.id}`,'PATCH',{version:rule.version,frequency,interval,reminder_time:remind?wall:null,title:seriesTitle}):
    api(`/workspace/tasks/${task.id}/recurrence`,'POST',{version:task.version,frequency,interval,anchor_on:anchor,reminder_time:remind?wall:null}),
    rule?'Правило для следующих экземпляров сохранено':'Повторение сохранено');}
  return <>
    {task.recurrence_warning?<Notice error>{task.recurrence_warning==='ambiguous_or_invalid_time'?'В день этого экземпляра выбранное время отсутствует или неоднозначно из-за перевода часов. Уведомление не назначено. Выберите другое точное время в форме дела.':'Время напоминания этого экземпляра уже прошло при настройке. Уведомление задним числом не создавалось; выберите новый момент.'}</Notice>:null}
    {task.kind!=='note'&&(active||rule)?<details className="detail-section recurrence-section"><summary>{rule?'Правило повторения':'Настроить повторение'}</summary>
      {rule?<><p className="recurrence-status">{rule.status==='active'?'Повторение активно':'Повторение остановлено'} · {rule.timezone}</p><p className="muted">День экземпляра: {task.occurrence_on}. Выполнение или отмена этого экземпляра не останавливает активное правило. Изменения ниже касаются следующих экземпляров.</p></>:
        <p className="muted">Отдельный экземпляр для каждого периода. Пропущенные периоды не копятся в очередь; незавершённое дело сохраняется.</p>}
      <form className="task-form" onSubmit={saveRule}><fieldset disabled={!!busy||!zone}>
        {rule?<label>Название следующих экземпляров<input required value={seriesTitle} maxLength={2000} onChange={e=>setSeriesTitle(e.target.value)}/></label>:
          <label>День этого экземпляра<input type="date" required value={anchor} onChange={e=>setAnchor(e.target.value)}/></label>}
        <div className="form-grid"><label>Повторять<select value={frequency} onChange={e=>setFrequency(e.target.value as typeof frequency)}><option value="daily">По дням</option><option value="weekly">По неделям</option><option value="monthly">По месяцам</option></select></label>
          <label>Интервал<input type="number" required min={1} max={365} value={interval} onChange={e=>setInterval(Number(e.target.value))}/></label></div>
        <label className="checkbox-label"><input type="checkbox" checked={remind} onChange={e=>setRemind(e.target.checked)}/>Точное уведомление для повторений</label>
        {remind?<label>Время повторяющегося уведомления<input type="time" required value={wall} onChange={e=>setWall(e.target.value)}/><small>{rule?.timezone || zone}. Время показано для проверки, пока не сохранено.</small></label>:<p className="muted">Точное уведомление не назначается. Дело появляется в обзоре в свой день.</p>}
        <p className="muted">Дедлайн текущего дела не переносится на следующие экземпляры. Уже назначенное уведомление текущего экземпляра сохраняется.</p>
        <button disabled={!!busy} className="primary">{rule?'Сохранить правило':'Сохранить повторение'}</button></fieldset></form>
      {rule?<button disabled={!!busy} className={rule.status==='active'?'danger-button':'text-button'} onClick={()=>run('status',()=>api(`/workspace/recurrences/${rule.id}`,'PATCH',
          {version:rule.version,status:rule.status==='active'?'stopped':'active'}),rule.status==='active'?'Повторение остановлено. Текущий экземпляр сохранён':'Повторение возобновлено')}>{rule.status==='active'?'Остановить повторение':'Возобновить повторение'}</button>:null}
      {!zone?<Notice error>Сначала задайте часовой пояс в настройках.</Notice>:null}
    </details>:null}
    <section className="detail-section step-plan"><h3>План небольших шагов</h3><p className="muted">Сначала черновик. Отдельные задачи появятся после подтверждения всего плана, без выдуманных сроков.</p>
      {active?<><label>Черновик шагов<textarea rows={4} maxLength={6012} value={steps} placeholder="Один шаг на строку, до 12 шагов" onChange={e=>setSteps(e.target.value)}/></label>
        <div className="button-row"><button disabled={!!busy||steps===task.draft_steps.join('\n')} onClick={()=>run('steps',()=>api(`/workspace/tasks/${task.id}/steps`,'PUT',
          {version:task.version,steps:steps.split('\n').map(s=>s.trim()).filter(Boolean)}),'Черновик шагов сохранён')}>Сохранить черновик шагов</button>
          {task.draft_steps.length&&!promoted?<button className="primary" disabled={!!busy||steps!==task.draft_steps.join('\n')} onClick={()=>run('confirm',()=>api(`/workspace/tasks/${task.id}/steps/confirm`,'POST',
            {version:task.version,request_id:request.current}),'Задачи из плана созданы')}>Создать {task.draft_steps.length} задачи из плана</button>:null}</div>
        {promoted?<p className="muted">Этот вариант плана уже подтверждён. Редактирование черновика потребует отдельного подтверждения нового набора.</p>:null}</>:<ol>{task.draft_steps.map((s,i)=><li key={i}>{s}</li>)}</ol>}
      {task.children?.length?<ul className="child-tasks">{task.children.map(child=><li key={child.id}><button className="text-button" disabled={!open} onClick={()=>open?.(child.id)}>{child.title}</button><span className={`state ${child.state}`}>{stateLabels[child.state]}</span></li>)}</ul>:null}
      {task.parent_task_id?<button className="text-button" disabled={!open} onClick={()=>open?.(task.parent_task_id!)}>Открыть родительское дело</button>:null}
    </section>{error?<Notice error>{error}</Notice>:null}
  </>;
}
