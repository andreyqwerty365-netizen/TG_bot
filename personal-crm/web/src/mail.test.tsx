import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MailEvidence, MailPanel } from './mail';

test('renders evidence as text and clearly flags unanalysed attachments', () => {
  const {container}=render(<MailEvidence zone="UTC" evidence={{subject:'Учебное письмо',sender:'sender@example.invalid',
    excerpt:'<img src="https://example.invalid/pixel">Пожалуйста, проверьте отчёт.',original_at:'2026-10-13T08:00:00Z',direction:'sent',attachments_unanalysed:true,content_incomplete:false}}/>);
  expect(screen.getByText('Отправленное письмо')).toBeTruthy();
  expect(screen.getByText(/Вложения не анализировались/)).toBeTruthy();
  expect(container.querySelectorAll('img,iframe,a')).toHaveLength(0);
});

test('disabled mailbox has no connect or sync action and displays seven-day read-only boundary',async()=>{
  const api=vi.fn().mockResolvedValue({available:false,status:'disabled',provider:null,read_only:true,window_days:7,poll_seconds:300,
    last_success_at:null,next_sync_at:null,error_code:null,failures:0,saved_count:0,reset_count:0});
  render(<MailPanel api={api} revision={0} changed={()=>{}} zone="UTC"/>);
  await waitFor(()=>expect(screen.getByText('Не подключена')).toBeTruthy());
  expect(screen.getByText(/Последние 7 дней/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Синхронизировать'})).toBeNull();
  expect(api).toHaveBeenCalledTimes(1);
});

test('sync reports a failure instead of announcing success',async()=>{
  const changed=vi.fn();
  const api=vi.fn().mockImplementation(async(_path:string,method='GET')=>method==='POST'?{status:'auth_error',saved:0}:
    {available:true,status:'idle',provider:'synthetic',read_only:true,window_days:7,poll_seconds:300,last_success_at:null,
      next_sync_at:null,error_code:null,failures:0,saved_count:0,reset_count:0});
  render(<MailPanel api={api} revision={0} changed={changed} zone="UTC"/>);
  await userEvent.click(await screen.findByRole('button',{name:'Синхронизировать'}));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(changed).not.toHaveBeenCalled();
});
