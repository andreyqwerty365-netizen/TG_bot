import { useState } from 'react';
import { displayDate, type Api } from './api';
import { Notice } from './components';

export function DataPanel({api}:{api:Api}) {
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  async function download() {
    setBusy(true);setError('');
    try {
      const data=await api('/workspace/export');
      const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
      const link=document.createElement('a');link.href=url;link.download='personal-crm-export.json';
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="panel"><span className="eyebrow">Мои данные</span><h2>Экспорт</h2>
    <p>Дела, заметки, сроки, источники, предложения и история в одном JSON-файле.</p>
    <p className="muted">Файл содержит ваши данные без шифрования. Сохраните его в защищённом месте. Зашифрованные резервные копии настраиваются отдельно на сервере.</p>
    <button disabled={busy} onClick={()=>void download()}>{busy?'Готовим файл…':'Скачать мои данные'}</button>
    {error?<Notice error>{error}</Notice>:null}</section>;
}

export function LegacyNotice({legacy,zone}:{legacy:{reminder_at:string|null;repeat_rule:string|null};zone:string|null}) {
  return <section className="panel"><h3>Из копии старого бота</h3><p>При импорте уведомления не запускались. Проверьте время и задайте нужное напоминание в этой карточке.</p>
    {legacy.reminder_at?<p>Исходное время напоминания: {displayDate(legacy.reminder_at,zone,true)}</p>:null}
    {legacy.repeat_rule?<p>Прежнее правило: <code>{legacy.repeat_rule}</code>. Проверьте его и настройте повторение заново.</p>:null}</section>;
}
