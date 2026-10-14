import { useEffect, useState } from 'react';
import { displayDate, type Api } from './api';
import { Notice } from './components';
import { useLoad } from './hooks';

type Health = {workers:Record<string,{status:string;last_seen_at?:string|null}>;
  queue:{pending:number;failed:number;unknown:number};backup:{status:string;last_verified_at:string|null}};
const labels:Record<string,string>={running:'Работает',idle:'Ожидает работу',disabled:'Выключено',
  missing:'Нет сигнала',stale:'Нет свежего сигнала',error:'Ошибка'};

export function OperationsPanel({api,revision,zone}:{api:Api;revision:number;zone:string|null}) {
  const [tick,setTick]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setTick(v=>v+1),30000);return()=>clearInterval(timer);},[]);
  const load=useLoad<Health>(api,'/workspace/system',revision+tick);
  const data=load.data;
  return <section className="panel"><h2>Работа CRM</h2>
    {load.error?<Notice error>{load.error}</Notice>:null}
    {!data?<p className="loading">Проверяем состояние…</p>:<>
      <dl className="connection-list">{[['source','Разбор сообщений'],['delivery','Доставка уведомлений'],['backup','Резервное копирование']].map(([role,title])=>
        <div key={role}><dt>{title}</dt><dd>{labels[data.workers[role]?.status] || 'Состояние неизвестно'}</dd></div>)}</dl>
      <p>В очереди: {data.queue.pending} · Ошибки: {data.queue.failed}</p>
      <p>Неопределённый исход: {data.queue.unknown}</p>
      {data.queue.unknown>0?<Notice>Проверьте фактическую доставку перед повторной отправкой.</Notice>:null}
      <p>{data.backup.status==='disabled'?'Внешние копии выключены.':data.backup.last_verified_at?
        `Последняя проверенная копия: ${displayDate(data.backup.last_verified_at,zone,true)}`:'Проверенной внешней копии пока нет.'}</p>
      {data.backup.status==='overdue'?<Notice error>Копии больше 26 часов. Проверьте резервное копирование.</Notice>:null}
      <small className="muted">Состояние обновляется каждые 30 секунд.</small>
    </>}
  </section>;
}
