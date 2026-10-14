import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('downloads the authenticated PostgreSQL export from settings',async({page},info)=>{
  await page.goto('./');
  await page.getByLabel('Ключ доступа').fill(process.env.CRM_WEB_TEST_TOKEN || 'synthetic-web-local');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Сегодня',exact:true})).toBeVisible();
  await page.getByRole('link',{name:'Настройки',exact:true}).click();
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'Скачать мои данные',exact:true}).click();
  const download=await downloadEvent;
  expect(download.suggestedFilename()).toBe('personal-crm-export.json');
  const data=JSON.parse(await readFile((await download.path())!,'utf-8'));
  expect(data.version).toBe(1);
  expect(data.records.tasks).toBeInstanceOf(Array);
  expect(data.records.profiles).toHaveLength(1);
  expect(JSON.stringify(data)).not.toContain('synthetic-web-local');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:`test-results/${info.project.name}-export.png`,fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
