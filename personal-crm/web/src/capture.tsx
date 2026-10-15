import { useRef,useState,type FormEvent } from 'react';
import type { Api } from './api';
import { Notice } from './components';
type Result={status:string;question?:string;task?:{id:string;title:string}};

export function QuickCapture({api,changed,open}:{api:Api;changed:(message:string)=>void;open:(id:string)=>void}) {
  const [text,setText]=useState('');const [answer,setAnswer]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [question,setQuestion]=useState<{id:string;text:string}|null>(null);const [result,setResult]=useState<Result|null>(null);
  const request=useRef(crypto.randomUUID());const reply=useRef(crypto.randomUUID());
  function received(value:Result,sourceId?:string) {
    setResult(value);
    if(value.status==='clarification'&&value.question){if(sourceId)setQuestion({id:sourceId,text:value.question});return;}
    setQuestion(null);setAnswer('');reply.current=crypto.randomUUID();
    if(value.status==='created'||value.status==='changed') {setText('');request.current=crypto.randomUUID();changed(value.status==='created'?'Дело сохранено':'Изменение сохранено');}
    else {changed(value.status==='proposal'?'Предложение сохранено':'Сообщение сохранено. Разбор ещё не завершён.');}
  }
  async function submit(e:FormEvent) {e.preventDefault();if(busy||!text.trim())return;setBusy(true);setError('');
    try {const value=await api<{source_version_id:string;result:Result}>('/workspace/capture','POST',{request_id:request.current,text});received(value.result,value.source_version_id);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function respond(e:FormEvent) {e.preventDefault();if(!question||busy||!answer.trim())return;setBusy(true);setError('');
    try {received(await api<Result>(`/workspace/sources/${question.id}/reply`,'POST',{request_id:reply.current,text:answer}),question.id);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <section className="panel capture-panel"><span className="eyebrow">Не потерять мысль</span><h2>Записать дело</h2>
    <form onSubmit={submit}><label className="sr-only" htmlFor="quick-capture">Быстро записать дело</label>
      <textarea id="quick-capture" rows={2} maxLength={16000} disabled={busy||!!question} value={text} placeholder="Например: завтра в 19:00 напомни обновить резюме"
        onChange={e=>{request.current=crypto.randomUUID();setText(e.target.value);setResult(null);}}
        onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/>
      <div className="capture-actions"><small>Enter — записать · Shift+Enter — новая строка</small><button className="primary" disabled={busy||!!question||!text.trim()}>{busy?'Сохраняем…':'Записать'}</button></div></form>
    {question?<form className="inline-form" onSubmit={respond}><p>{question.text}</p><label>Ответ на вопрос<input autoFocus value={answer} disabled={busy} onChange={e=>{reply.current=crypto.randomUUID();setAnswer(e.target.value);}}/></label><button disabled={busy||!answer.trim()}>Ответить</button>
      <button type="button" className="text-button" disabled={busy} onClick={()=>{setQuestion(null);setResult(null);setText('');request.current=crypto.randomUUID();}}>Новое сообщение</button></form>:null}
    {error?<Notice error>{error}</Notice>:null}
    {result?.task&&!question?<p role="status">{result.status==='created'?'Сохранено: ':result.status==='changed'?'Изменено: ':''}<button className="text-button" onClick={()=>open(result.task!.id)}>{result.task.title}</button></p>:null}
    {result?.status==='proposal'?<p>Нужно ваше подтверждение. <a href="#inbox">Открыть входящие</a></p>:null}
    {result&&['processing','error','pending'].includes(result.status)?<Notice>Сообщение сохранено. <a href="#inbox">Проверить разбор во входящих</a></Notice>:null}
    <p className="muted">Для точных полей и проектов используйте «Добавить дело». Сложная формулировка может потребовать уточнения.</p></section>;
}
