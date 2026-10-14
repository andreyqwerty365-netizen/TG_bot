import { test, expect } from '@playwright/test';

// Requires the explicitly guarded synthetic laboratory factory + source worker.
test('synchronises synthetic mail and creates a task only after confirmation',async({page,request},info)=>{
  const headers={Authorization:'Bearer '+(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local')};
  const status=await (await request.get('/workspace/mail',{headers})).json();
  expect(status.provider).toBe('synthetic');
  await page.goto('./#settings');
  await page.getByLabel('Пароль').fill(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.getByText('Синтетический стенд. Реальный ящик не подключён.')).toBeVisible();
  await page.getByRole('button',{name:'Синхронизировать',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Сохранено новых редакций: 3');
  const updated=await (await request.get('/workspace/mail',{headers})).json();
  const sequence=updated.saved_count/3;
  const title=`Почтовая проверка ${sequence}`;
  await expect.poll(async()=>{
    const inbox=await(await request.get('/workspace/inbox',{headers})).json();
    return inbox.proposals.some((p:{payload:{title:string}})=>p.payload.title===title);
  },{timeout:15000}).toBe(true);
  let tasks=await(await request.get('/workspace/tasks?q='+encodeURIComponent(title),{headers})).json();
  expect(tasks.total).toBe(0);
  await page.getByRole('link',{name:'Входящие',exact:true}).click();
  const proposal=page.locator('article').filter({has:page.getByRole('heading',{name:title,exact:true})});
  await expect(proposal.getByText('Пожалуйста, проверьте учебный отчёт. Это синтетическое письмо.',{exact:true})).toBeVisible();
  await expect(proposal.getByText(/Вложения не анализировались/)).toBeVisible();
  await page.screenshot({path:`test-results/${info.project.name}-mail.png`,fullPage:true});
  await proposal.getByRole('button',{name:'Принять',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Предложение принято');
  tasks=await(await request.get('/workspace/tasks?q='+encodeURIComponent(title),{headers})).json();
  expect(tasks.total).toBe(1);expect(tasks.items[0].state).toBe('active');
  await page.reload();
  await expect(page.getByLabel('Пароль')).not.toBeVisible();
  await page.getByRole('link',{name:'Все дела',exact:true}).click();
  await page.getByLabel('Найти дело').fill(title);
  await expect(page.getByRole('button',{name:title,exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
