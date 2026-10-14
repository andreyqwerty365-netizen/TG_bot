import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, test, expect } from 'vitest';
import App from './App';

const task = { id: 'synthetic-task', title: 'Синтетическое дело', state: 'active', kind: 'task', version: 1,
  deadline: null, planned_on: null, reminder_at: null, project_id: null, draft_steps: [], focused: false };
const prefs = { version: 1, timezone: 'Europe/Moscow', digest_hour: 12, initiative_limit: 2, catchup_grace_seconds: 3600,
  integrations: { openai: false, mail: false, telegram_receive: false, telegram_send: false }, ai: { model: '', configured_budget_usd: '0', consent_categories: [], budget: { spent_micro_usd: 0, reserved_micro_usd: 0 } } };
function apiMock() {
  const calls: {path:string; body?:unknown}[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({path, body:init?.body ? JSON.parse(String(init.body)) : undefined});
    let body: unknown = path.includes('/settings') ? prefs : path.includes('/projects') ? [] : path.includes('/inbox') ? { proposals: [], questions: [], errors: [] } :
      path === '/overview' ? { main: [task], deadlines: [], forgotten: [], waiting: [], proposals: [], guidance: [], other_count: 0 } :
      path.includes('/workspace/tasks?') ? {items:[task], total:1, offset:0, limit:30} : task;
    if (path === '/workspace/tasks' && init?.method === 'POST') body = {...task, title:JSON.parse(String(init.body)).title};
    return {ok:true, status:200, json:async()=>body};
  }));
  return calls;
}

test('authenticates before loading real task data and does not persist credentials', async () => {
  apiMock();
  render(<App/>);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Ключ доступа'), 'synthetic-web-secret');
  await user.click(screen.getByRole('button', {name:'Войти'}));
  expect(await screen.findByText('Синтетическое дело')).toBeTruthy();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

test('manual task form sends title and calendar fields to backend', async () => {
  const calls = apiMock();
  render(<App/>);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Ключ доступа'), 'synthetic-web-secret');
  await user.click(screen.getByRole('button', {name:'Войти'}));
  await screen.findByText('Синтетическое дело');
  await user.click(screen.getByRole('button', {name:'Добавить дело'}));
  await user.type(screen.getByLabelText('Название'), 'Новое синтетическое дело');
  await user.click(screen.getByRole('button', {name:'Сохранить дело'}));
  await waitFor(() => expect(calls.some(c => c.path === '/workspace/tasks' && (c.body as {title?:string})?.title === 'Новое синтетическое дело')).toBe(true));
});

test('search sends query to server rather than filtering a local task copy', async () => {
  const calls = apiMock();
  render(<App/>);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Ключ доступа'), 'synthetic-web-secret');
  await user.click(screen.getByRole('button', {name:'Войти'}));
  await screen.findByText('Синтетическое дело');
  await user.click(screen.getByRole('link', {name:'Все дела'}));
  await user.type(screen.getByLabelText('Найти дело'), 'старое');
  await waitFor(() => expect(calls.some(c => c.path.includes('q=%D1%81%D1%82%D0%B0%D1%80%D0%BE%D0%B5'))).toBe(true));
});
