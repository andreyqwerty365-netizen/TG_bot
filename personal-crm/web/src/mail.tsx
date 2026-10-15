import { useState, type FormEvent } from 'react';
import { displayDate, type Api, type MailEvidenceData, type MailStatus } from './api';
import { useLoad } from './hooks';
import { Notice } from './components';

export function MailEvidence({evidence,zone}:{evidence:MailEvidenceData;zone:string|null}) {
  return <div className="mail-evidence"><div className="mail-evidence-heading"><span className="eyebrow">{evidence.direction==='sent'?'Отправленное письмо':'Входящее письмо'}</span>
    {evidence.original_at?<time dateTime={evidence.original_at}>{displayDate(evidence.original_at,zone,true)}</time>:null}</div>
    <p><strong>{evidence.subject || 'Без темы'}</strong></p>{evidence.sender?<p className="muted">От: {evidence.sender}</p>:null}
    <blockquote className="source-text">{evidence.excerpt || 'Доступного текста нет.'}</blockquote>
    {evidence.attachments_unanalysed?<p className="mail-caution">Вложения не анализировались. Проверьте их отдельно в почтовом клиенте.</p>:null}
    {evidence.content_incomplete?<p className="mail-caution">Текст получен не полностью или его формат не поддерживается.</p>:null}
    {evidence.direction==='sent'?<p className="muted">Отправка письма сама по себе не подтверждает выполнение дела.</p>:null}
  </div>;
}

export function MailPanel({api,revision,changed,zone}:{api:Api;revision:number;changed:(message:string)=>void;zone:string|null}) {
  const [refresh,setRefresh]=useState(0);const load=useLoad<MailStatus>(api,'/workspace/mail',revision+refresh);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const state=load.data;
  const names={disabled:'Не подключена',idle:'Ожидает следующей сверки',syncing:'Идёт синхронизация',backoff:'Повтор отложен',auth_error:'Доступ отклонён',error:'Синхронизация остановлена'};
  async function action(name:'sync'|'disconnect') {setBusy(true);setError('');try {
    const result=await api<{status:string;saved?:number}>(`/workspace/mail/${name}`,'POST');
    if(['auth_error','error','backoff','superseded'].includes(result.status)) {setError(result.status==='auth_error'?'Почтовый сервер отклонил доступ. Проверьте серверную настройку; письма пока не обновлены.':'Синхронизация не завершена. Сохранённые данные доступны.');setRefresh(v=>v+1);return;}
    if(result.status==='busy'){setError('Синхронизация уже выполняется. Обновите состояние через некоторое время.');return;}
    changed(name==='disconnect'?'Чтение почты отключено':result.status==='disabled'?'Чтение почты выключено':`Сохранено новых редакций: ${result.saved || 0}. Разбор выполняется фоновым обработчиком.`);
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <section className="panel mail-panel"><header className="section-heading"><h2>Почта</h2><span className="mail-badge">Только чтение</span></header>
    <p className="muted">Последние 7 дней · входящие и отправленные · сверка каждые 5 минут.</p>
    {load.error?<Notice error>{load.error}</Notice>:load.loading?<p className="loading">Проверяем состояние…</p>:state?<>
      <p className="mail-state"><span className={`mail-state-dot ${state.status}`}/>{names[state.status]}</p>
      {state.provider==='synthetic'?<p className="mail-caution">Синтетический стенд. Реальный ящик не подключён.</p>:null}
      {state.error_code?<Notice error>{state.status==='auth_error'?'Доступ отозван или отклонён. Автоматическая сверка остановлена.':'Сверка задержана; после трёх неудач автоматические повторы останавливаются.'}</Notice>:null}
      {state.last_success_at?<p>Последняя успешная сверка: {displayDate(state.last_success_at,zone,true)}</p>:null}
      {state.next_sync_at&&state.status==='backoff'?<p>Следующая попытка: {displayDate(state.next_sync_at,zone,true)}</p>:null}
      <p className="muted">Сохранено редакций писем: {state.saved_count}. Восстановлений курсора: {state.reset_count}.</p>
      {!state.available?<p>Реальный ящик пока не подключён. Его адрес, провайдер и доступ задаются отдельно на сервере с явным разрешением чтения.</p>:null}
      <div className="button-row">{state.available&&state.status!=='disabled'?<><button disabled={busy||state.status==='syncing'} onClick={()=>action('sync')}>{busy?'Выполняем…':'Синхронизировать'}</button><button disabled={busy} onClick={()=>action('disconnect')}>Отключить чтение</button></>:null}
        <button className="text-button" disabled={busy} onClick={()=>setRefresh(v=>v+1)}>Обновить состояние</button></div>
    </>:null}{error?<Notice error>{error}</Notice>:null}
    <p className="muted">Предложения требуют вашего решения. Письма не отправляются, не удаляются и не помечаются прочитанными.</p>
  </section>;
}

export function MailReview({id,evidence,api,zone,changed}:{id:string;evidence:MailEvidenceData;api:Api;zone:string|null;changed:(message:string)=>void}) {
  const [title,setTitle]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  async function submit(e:FormEvent){e.preventDefault();setBusy(true);setError('');try{await api(`/workspace/mail/reviews/${id}/propose`,'POST',{title});changed('Предложение подготовлено. Проверьте его перед принятием.');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <article className="inbox-item"><span className="eyebrow">Нужен ваш просмотр</span><h3>Действие из письма не определено</h3><MailEvidence evidence={evidence} zone={zone}/>
    <form className="task-form" onSubmit={submit}><fieldset disabled={busy}><label>Предлагаемое дело<input required maxLength={2000} value={title} onChange={e=>setTitle(e.target.value)}/></label>
    <div className="button-row"><button className="primary">Создать предложение</button><button type="button" onClick={async()=>{setBusy(true);try{await api(`/workspace/mail/reviews/${id}/dismiss`,'POST');changed('Письмо просмотрено');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Не требует дела</button></div></fieldset></form>{error?<Notice error>{error}</Notice>:null}</article>;
}
