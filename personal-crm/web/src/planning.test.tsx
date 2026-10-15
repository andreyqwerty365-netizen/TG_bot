import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { PlanningBoard, TaskPlanning } from './planning';
import type { Api, Detail } from './api';

const task:Detail={id:'synthetic-plan-parent',title:'Учебное дело',version:3,state:'active',kind:'task',draft_steps:['Открыть файл','Проверить итог'],
  steps_revision:2,promoted_steps_revision:null,recurrence:null,children:[],planned_on:null,deadline:null,project_id:null,focused:false,
  source:{id:'synthetic-source',text:'Учебное дело',channel:'owner',received_at:'2026-10-14T08:00:00Z'},history:[]};

test('draft plan does not create children before explicit whole-plan confirmation',async()=>{
  const api=vi.fn().mockResolvedValue({children:[]});
  render(<TaskPlanning task={task} api={api as Api} zone="Europe/Moscow" preferredTime={null} changed={()=>{}}/>);
  expect(api).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button',{name:'Создать 2 задачи из плана'}));
  expect(api).toHaveBeenCalledWith('/workspace/tasks/synthetic-plan-parent/steps/confirm','POST',expect.objectContaining({version:3,request_id:expect.any(String)}));
});

test('recurrence requires an explicit date and does not invent a reminder time',async()=>{
  const api=vi.fn().mockResolvedValue({});
  render(<TaskPlanning task={{...task,draft_steps:[]}} api={api as Api} zone="Europe/Moscow" preferredTime={null} changed={()=>{}}/>);
  await userEvent.click(screen.getByText('Настроить повторение'));
  await userEvent.type(screen.getByLabelText('День этого экземпляра'),'2026-10-14');
  await userEvent.click(screen.getByRole('button',{name:'Сохранить повторение'}));
  expect(api).toHaveBeenCalledWith('/workspace/tasks/synthetic-plan-parent/recurrence','POST',expect.objectContaining({version:3,anchor_on:'2026-10-14',reminder_time:null}));
});

test('early plan and reminder preference stay suggestions until a deliberate action',async()=>{
  const api=vi.fn().mockResolvedValue({status:'accepted'});
  render(<PlanningBoard items={[{id:'early-synthetic',version:2,kind:'early',task_id:'synthetic-plan-parent',payload:{title:'Учебное дело',planned_on:'2026-10-18',deadline:{value:'2026-10-20'}}}]}
    api={api as Api} changed={()=>{}} zone="Europe/Moscow"/>);
  expect(screen.getByText(/Внешний срок остаётся/)).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button',{name:'Принять план'}));
  expect(api).toHaveBeenCalledWith('/workspace/suggestions/early-synthetic/confirm','POST',{version:2,accept:true});
});
