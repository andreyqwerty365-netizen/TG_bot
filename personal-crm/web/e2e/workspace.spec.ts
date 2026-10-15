import { test, expect } from '@playwright/test';

async function login(page:import('@playwright/test').Page) {
  const session=page.waitForResponse(r=>r.url().endsWith('/auth/session'));
  await page.goto('./');
  if(!(await session).ok()){
    await page.getByLabel('Пароль').fill(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local');
    await page.getByRole('button',{name:'Войти',exact:true}).click();
  }
  await expect(page.getByRole('heading',{name:'Сегодня',exact:true})).toBeVisible();
}

test('creates, searches, edits and completes a real PostgreSQL task', async ({page,request},info)=>{
  await login(page);
  const title=`Синтетическое веб-дело ${info.project.name} ${Date.now()}`;
  await page.getByRole('button',{name:'Добавить дело',exact:true}).click();
  await page.getByLabel('Название',{exact:true}).fill(title);
  await page.getByLabel('Напомнить в').fill('2026-11-01T19:00');
  await page.getByRole('button',{name:'Сохранить дело',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Дело сохранено');
  await page.getByRole('link',{name:'Все дела',exact:true}).click();
  await page.getByLabel('Найти дело').fill(title);
  await page.getByRole('button',{name:title,exact:true}).click();
  await page.getByLabel('Название',{exact:true}).fill(title+' — правка');
  await page.getByLabel('Напомнить в').fill('2026-11-01T20:00');
  await page.getByRole('button',{name:'Сохранить изменения',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Изменения сохранены');
  await page.getByLabel('Найти дело').fill(title+' — правка');
  await page.getByRole('button',{name:title+' — правка',exact:true}).click();
  await expect(page.getByText('Синтетическое веб-дело',{exact:false}).first()).toBeVisible();
  await page.getByRole('button',{name:'Выполнить дело',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Дело выполнено');
  const response=await request.get('/workspace/tasks?q='+encodeURIComponent(title),{headers:{Authorization:'Bearer '+(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local')}});
  const result=await response.json();
  expect(result.items).toHaveLength(1);
  expect(result.items[0].state).toBe('done');
  expect(result.items[0].reminder_at).toBeNull();
  await page.screenshot({path:`test-results/${info.project.name}-tasks.png`,fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('persists a project and resolves a saved clarification',async({page,request},info)=>{
  await login(page);
  const name=`Учебный проект ${info.project.name} ${Date.now()}`;
  await page.getByRole('link',{name:'Проекты',exact:true}).click();
  await page.getByRole('button',{name:'Создать проект',exact:true}).click();
  await page.getByLabel('Название проекта').fill(name);
  await page.getByRole('button',{name:'Сохранить проект',exact:true}).click();
  await expect(page.getByRole('button',{name,exact:true})).toBeVisible();
  const response=await request.post('/sources',{headers:{Authorization:'Bearer '+(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local')},data:{account:'synthetic-e2e-'+info.project.name,external_id:String(Date.now()),text:'Завтра напомни обновить резюме'}});
  expect((await response.json()).status).toBe('clarification');
  await page.getByRole('link',{name:'Входящие',exact:true}).click();
  await page.getByLabel('Ответ на уточнение').first().fill('в 19:00');
  await page.getByRole('button',{name:'Ответить',exact:true}).first().click();
  await expect(page.getByRole('status')).toContainText('Дело сохранено');
  await page.reload();
  await login(page);
  await page.getByRole('link',{name:'Проекты',exact:true}).click();
  await expect(page.getByRole('button',{name,exact:true})).toBeVisible();
});

test('persists notification preferences and AI pause through reload',async({page})=>{
  await login(page);
  await page.getByRole('link',{name:'Настройки',exact:true}).click();
  await page.getByLabel('Час ежедневной сводки').fill('9');
  await page.getByLabel('Дополнительные напоминания в сутки').selectOption('1');
  await page.getByLabel('Приостановить разбор с ИИ').check();
  await page.getByLabel('Мой месячный лимит ИИ, USD').fill('0');
  await page.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Настройки сохранены');
  await login(page);
  await page.getByRole('link',{name:'Настройки',exact:true}).click();
  await expect(page.getByLabel('Час ежедневной сводки')).toHaveValue('9');
  await expect(page.getByLabel('Дополнительные напоминания в сутки')).toHaveValue('1');
  await expect(page.getByLabel('Приостановить разбор с ИИ')).toBeChecked();
});

test('stale web edit cannot overwrite a concurrent PostgreSQL change',async({page,request},info)=>{
  const title=`Конкурентное синтетическое дело ${info.project.name} ${Date.now()}`;
  const auth={Authorization:'Bearer '+(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local')};
  const response=await request.post('/workspace/tasks',{headers:auth,data:{request_id:title,title}});
  const task=await response.json();
  await login(page);
  await page.getByRole('link',{name:'Все дела',exact:true}).click();
  await page.getByLabel('Найти дело').fill(title);
  await page.getByRole('button',{name:title,exact:true}).click();
  await page.getByLabel('Название',{exact:true}).fill('Мой несохранённый черновик');
  const concurrent=await request.patch(`/workspace/tasks/${task.id}`,{headers:auth,data:{version:task.version,title:title+' — другая правка'}});
  expect(concurrent.ok()).toBe(true);
  await page.getByRole('button',{name:'Сохранить изменения',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Дело уже изменилось');
  const current=await request.get(`/workspace/tasks/${task.id}`,{headers:auth});
  expect((await current.json()).title).toBe(title+' — другая правка');
});
