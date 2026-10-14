import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { makeApi, type Preferences, type Project } from './api';
import { useLoad } from './hooks';
import { Dialog, Notice, TaskDialog, TaskForm } from './components';
import { AllTasks, Incoming, Projects, SettingsScreen, Today } from './screens';

const sections=[{key:'today',label:'Сегодня',icon:'◷',subtitle:'Выберите главное и сделайте следующий шаг.'},
  {key:'all',label:'Все дела',icon:'≡',subtitle:'Всё, что важно сохранить и довести до результата.'},
  {key:'inbox',label:'Входящие',icon:'↳',subtitle:'Разберите предложения и уточните недостающее.'},
  {key:'projects',label:'Проекты',icon:'▱',subtitle:'Связанные дела, собранные в одном месте.'},
  {key:'settings',label:'Настройки',icon:'⚙',subtitle:'Ваш ритм, подключённые источники и расходы.'}];
function routeFromHash(){const hash=window.location.hash.slice(1);return sections.some(s=>s.key===hash)?hash:'today';}

function Login({enter}:{enter:(token:string)=>void}) {
  const [key,setKey]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  async function submit(e:FormEvent){e.preventDefault();setBusy(true);setError('');try{await makeApi(key)<Preferences>('/workspace/settings');enter(key);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <main className="login-page"><section className="login-intro"><div className="brand"><span className="brand-symbol" aria-hidden="true">p</span><span>Personal <strong>CRM</strong></span></div>
    <span className="eyebrow">Личное пространство для дел</span><h1>Освободите голову.<br/>Сохраните важное.</h1><p>Задачи, ожидания и следующие шаги — рядом, когда они нужны.</p><div className="login-line" aria-hidden="true"><i/><i/><i/></div></section>
    <section className="login-form"><span className="eyebrow">С возвращением</span><h2>Войти в мои дела</h2><p>Используйте ключ доступа владельца, заданный при локальной настройке приложения.</p>
      <form onSubmit={submit}><label>Ключ доступа<input type="password" autoComplete="current-password" required autoFocus value={key} onChange={e=>setKey(e.target.value)} disabled={busy}/></label>{error?<Notice error>{error}</Notice>:null}<button className="primary" disabled={busy}>{busy?'Проверяем доступ…':'Войти'}</button></form>
      <small>Ключ хранится в памяти этой вкладки. После обновления страницы потребуется войти снова.</small></section></main>;
}

function Workspace({token,logout}:{token:string;logout:()=>void}) {
  const api=useMemo(()=>makeApi(token),[token]);const [route,setRoute]=useState(routeFromHash);const [revision,setRevision]=useState(0);const [toast,setToast]=useState('');
  const [adding,setAdding]=useState(false);const [selected,setSelected]=useState<string|null>(null);const [projectFilter,setProjectFilter]=useState('');
  const settings=useLoad<Preferences>(api,'/workspace/settings',revision);const projects=useLoad<Project[]>(api,'/workspace/projects',revision);
  useEffect(()=>{const update=()=>setRoute(routeFromHash());window.addEventListener('hashchange',update);return ()=>window.removeEventListener('hashchange',update);},[]);
  function navigate(key:string,project=''){setProjectFilter(project);setRoute(key);window.location.hash=key;}
  function changed(message:string){setToast(message);setRevision(v=>v+1);}
  const prefs=settings.data;const projectRows=projects.data || [];const section=sections.find(s=>s.key===route)!;
  const today=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',timeZone:prefs?.timezone || 'UTC'}).format(new Date());
  const props=prefs?{api,preferences:prefs,projects:projectRows,revision,open:setSelected,changed}:null;
  return <div className="app-shell"><a className="skip-link" href="#main-content">К содержимому</a><aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true">p</span><span>Personal <strong>CRM</strong></span></div><p className="sidebar-label">Моё пространство</p>
    <nav aria-label="Основные разделы">{sections.map(s=><a key={s.key} href={`#${s.key}`} aria-current={route===s.key?'page':undefined} onClick={e=>{e.preventDefault();navigate(s.key);}}><span aria-hidden="true">{s.icon}</span>{s.label}</a>)}</nav>
    <div className="sidebar-bottom"><div className="workspace-owner"><span aria-hidden="true">P</span><div><strong>Личные дела</strong><small>Только для владельца</small></div></div><button onClick={logout}>Выйти</button></div></aside>
    <main id="main-content" className="workspace" tabIndex={-1}><header className="page-header"><div><p className="date-line">{today}</p><h1 id="page-title" tabIndex={-1}>{section.label}</h1><p>{section.subtitle}</p></div><button className="primary add-button" onClick={()=>setAdding(true)} disabled={!prefs}><span aria-hidden="true">＋</span>Добавить дело</button></header>
      {toast?<div className="toast" role="status"><span aria-hidden="true">✓</span>{toast}<button aria-label="Скрыть уведомление" onClick={()=>setToast('')}>×</button></div>:null}
      {settings.error?<Notice error>{settings.error}</Notice>:null}{projects.error?<Notice error>{projects.error}<button onClick={()=>setRevision(v=>v+1)}>Повторить загрузку</button></Notice>:null}
      {!prefs?<p className="loading">Загружаем ваше пространство…</p>:props?route==='today'?<Today {...props}/>:route==='all'?<AllTasks key={projectFilter} {...props} initialProject={projectFilter}/>:route==='inbox'?<Incoming {...props}/>:route==='projects'?<Projects {...props} showTasks={id=>navigate('all',id)}/>:<SettingsScreen key={prefs.version} {...props}/>:null}
      <footer className="workspace-footer">Personal CRM<span>{prefs?.timezone || 'Часовой пояс не задан'}</span><button className="text-button" onClick={()=>setRevision(v=>v+1)}>Обновить данные</button><button className="text-button mobile-logout" onClick={logout}>Выйти</button></footer>
    </main>
    {adding&&prefs?<Dialog title="Новое дело" close={()=>setAdding(false)}><TaskForm projects={projectRows} zone={prefs.timezone} onSave={async values=>{await api('/workspace/tasks','POST',values);changed('Дело сохранено');setAdding(false);}}/></Dialog>:null}
    {selected&&prefs?<TaskDialog id={selected} api={api} revision={revision} preferences={prefs} projects={projectRows} close={()=>setSelected(null)} changed={changed}/>:null}
  </div>;
}

export default function App(){const [token,setToken]=useState('');return token?<Workspace token={token} logout={()=>setToken('')}/>:<Login enter={setToken}/>;}
