import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Api, Overview, Preferences } from './api';
import { Today } from './screens';

const overview:Overview={main:[],deadlines:[],forgotten:[],waiting:[],proposals:[],guidance:[],other_count:0};
const preferences={timezone:'Europe/Moscow'} as Preferences;

test('overview refresh preserves an unsent capture and recovers from a failed overview',async()=>{
  let rejectRefresh:(error:Error)=>void=()=>{};
  const api=vi.fn().mockResolvedValueOnce(overview)
    .mockImplementationOnce(()=>new Promise((_,reject)=>{rejectRefresh=reject;}))
    .mockResolvedValue(overview);
  const props={api:api as Api,preferences,projects:[],revision:0,open:vi.fn(),changed:vi.fn()};
  const view=render(<Today {...props}/>);
  await screen.findByText('Можно начать с одного дела');
  await userEvent.type(screen.getByLabelText('Быстро записать дело'),'Проверить документ');
  view.rerender(<Today {...props} revision={1}/>);
  expect((screen.getByLabelText('Быстро записать дело') as HTMLTextAreaElement).value).toBe('Проверить документ');
  await waitFor(()=>expect(api).toHaveBeenCalledTimes(2));
  rejectRefresh(new Error('Обзор недоступен'));
  await screen.findByText('Обзор недоступен');
  expect((screen.getByLabelText('Быстро записать дело') as HTMLTextAreaElement).value).toBe('Проверить документ');
  await userEvent.click(screen.getByRole('button',{name:'Повторить загрузку обзора'}));
  await screen.findByText('Можно начать с одного дела');
  expect((screen.getByLabelText('Быстро записать дело') as HTMLTextAreaElement).value).toBe('Проверить документ');
});

test('saved capture result survives the overview refresh caused by saving',async()=>{
  const api=vi.fn(async(path:string)=>path==='/workspace/capture'
    ? {source_version_id:'synthetic-source',result:{status:'created',task:{id:'synthetic-task',title:'Проверить документ'}}}
    : overview);
  const props={api:api as Api,preferences,projects:[],revision:0,open:vi.fn(),changed:vi.fn()};
  const view=render(<Today {...props}/>);
  await screen.findByText('Можно начать с одного дела');
  await userEvent.type(screen.getByLabelText('Быстро записать дело'),'Проверить документ{Enter}');
  await waitFor(()=>expect(props.changed).toHaveBeenCalledWith('Дело сохранено'));
  view.rerender(<Today {...props} revision={1}/>);
  await screen.findByText('Можно начать с одного дела');
  await userEvent.click(screen.getByRole('button',{name:'Проверить документ'}));
  expect(props.open).toHaveBeenCalledWith('synthetic-task');
});
