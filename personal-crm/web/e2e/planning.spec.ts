import { test, expect } from '@playwright/test';

const headers={Authorization:'Bearer '+(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local')};
async function openTask(page:import('@playwright/test').Page,title:string){
  await page.goto('./');await page.getByLabel('Пароль').fill(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await page.getByRole('link',{name:'Все дела',exact:true}).click();
  await page.getByLabel('Найти дело').fill(title);
  await page.getByRole('button',{name:title,exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Карточка дела'})).toHaveCSS('background-color','rgb(255, 255, 255)');
}

test('completes one recurring instance, keeps next one and stops the rule explicitly',async({page,request},info)=>{
  const title=`Учебная регулярная проверка ${info.project.name} ${Date.now()}`;
  const created=await request.post('/workspace/tasks',{headers,data:{request_id:title,title}});
  expect(created.ok()).toBe(true);
  await openTask(page,title);
  await page.getByText('Настроить повторение',{exact:true}).click();
  await page.getByLabel('День этого экземпляра').fill('2026-11-01');
  await page.getByRole('button',{name:'Сохранить повторение',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Повторение сохранено');
  await page.getByRole('button',{name:'Выполнить экземпляр',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Дело выполнено');
  const tasks=await(await request.get('/workspace/tasks?q='+encodeURIComponent(title),{headers})).json();
  expect(tasks.total).toBe(2);
  const next=tasks.items.find((task:{state:string})=>task.state==='active');
  expect(next.occurrence_on).toBe('2026-11-02');expect(next.deadline).toBeNull();expect(next.reminder_at).toBeNull();
  await page.getByRole('combobox',{name:'Состояние',exact:true}).selectOption('active');
  await page.getByRole('button',{name:title,exact:true}).click();
  await page.getByText('Правило повторения',{exact:true}).click();
  await page.getByRole('button',{name:'Остановить повторение',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Повторение остановлено');
  await page.getByText('Правило повторения',{exact:true}).click();
  await expect(page.getByText(/Повторение остановлено ·/)).toBeVisible();
  await page.screenshot({path:`test-results/${info.project.name}-recurrence.png`,fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test('saves draft steps, confirms the whole plan once and follows the child task',async({page,request},info)=>{
  const title=`Учебный план ${info.project.name} ${Date.now()}`;
  const created=await(await request.post('/workspace/tasks',{headers,data:{request_id:title,title}})).json();
  await openTask(page,title);
  const first=`Открыть учебный файл ${info.project.name} ${Date.now()}`;
  const second=`Сверить учебный итог ${info.project.name} ${Date.now()}`;
  await page.getByLabel('Черновик шагов').fill(`${first}\n${second}`);
  await page.getByRole('button',{name:'Сохранить черновик шагов',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Черновик шагов сохранён');
  let detail=await(await request.get(`/workspace/tasks/${created.id}`,{headers})).json();
  expect(detail.children).toHaveLength(0);
  await page.getByRole('button',{name:'Создать 2 задачи из плана',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Задачи из плана созданы');
  detail=await(await request.get(`/workspace/tasks/${created.id}`,{headers})).json();
  expect(detail.children).toHaveLength(2);
  expect(detail.children.every((child:{deadline:unknown;reminder_at:unknown})=>child.deadline===null)).toBe(true);
  expect(detail.state).toBe('active');
  await page.getByRole('button',{name:first,exact:true}).click();
  await expect(page.getByLabel('Название',{exact:true})).toHaveValue(first);
  await page.getByRole('button',{name:'Открыть родительское дело',exact:true}).click();
  await expect(page.getByLabel('Название',{exact:true})).toHaveValue(title);
  await page.getByRole('heading',{name:'План небольших шагов',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:`test-results/${info.project.name}-steps.png`,fullPage:true});
});
