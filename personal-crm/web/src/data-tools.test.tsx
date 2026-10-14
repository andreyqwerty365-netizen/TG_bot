import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Api } from './api';
import { DataPanel, LegacyNotice } from './data-tools';

test('export waits for a deliberate click and reports authorization errors',async()=>{
  const api=vi.fn().mockRejectedValue(new Error('Нет доступа к экспорту'));
  render(<DataPanel api={api as Api}/>);
  expect(api).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button',{name:'Скачать мои данные'}));
  expect(api).toHaveBeenCalledWith('/workspace/export');
  expect(await screen.findByText('Нет доступа к экспорту')).toBeTruthy();
});

test('imported reminder and repeat are shown as original evidence requiring review',()=>{
  render(<LegacyNotice legacy={{reminder_at:'2026-10-15T09:00:00Z',repeat_rule:'daily'}} zone="Europe/Moscow"/>);
  expect(screen.getByText(/При импорте уведомления не запускались/)).toBeTruthy();
  expect(screen.getByText(/daily/)).toBeTruthy();
});
