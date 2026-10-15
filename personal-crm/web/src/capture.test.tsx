import { render,screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect,test,vi } from 'vitest';
import type { Api } from './api';
import { QuickCapture } from './capture';

test('lost response preserves text and request identity for a safe retry',async()=>{
  const api=vi.fn().mockRejectedValueOnce(new Error('Связь потеряна')).mockResolvedValueOnce({source_version_id:'synthetic-source',result:{status:'created',task:{id:'synthetic-task',title:'Учебное дело'}}});
  render(<QuickCapture api={api as Api} changed={()=>{}} open={()=>{}}/>);
  await userEvent.type(screen.getByLabelText('Быстро записать дело'),'Учебное дело');
  await userEvent.click(screen.getByRole('button',{name:'Записать'}));
  expect(await screen.findByText('Связь потеряна')).toBeTruthy();
  expect((screen.getByLabelText('Быстро записать дело') as HTMLTextAreaElement).value).toBe('Учебное дело');
  await userEvent.click(screen.getByRole('button',{name:'Записать'}));
  expect(api.mock.calls[0][2].request_id).toBe(api.mock.calls[1][2].request_id);
});

test('clarification is answered inline and only a committed task is announced',async()=>{
  const changed=vi.fn();const api=vi.fn().mockResolvedValueOnce({source_version_id:'synthetic-source',result:{status:'clarification',question:'Во сколько?'}})
    .mockResolvedValueOnce({status:'created',task:{id:'synthetic-task',title:'Учебное дело'}});
  render(<QuickCapture api={api as Api} changed={changed} open={()=>{}}/>);
  await userEvent.type(screen.getByLabelText('Быстро записать дело'),'Завтра напомни учебное дело{Enter}');
  expect(await screen.findByText('Во сколько?')).toBeTruthy();
  expect(changed).not.toHaveBeenCalledWith('Дело сохранено');
  await userEvent.type(screen.getByLabelText('Ответ на вопрос'),'в 19:00');
  await userEvent.click(screen.getByRole('button',{name:'Ответить'}));
  expect(api).toHaveBeenLastCalledWith('/workspace/sources/synthetic-source/reply','POST',expect.objectContaining({text:'в 19:00'}));
  expect(changed).toHaveBeenLastCalledWith('Дело сохранено');
});
