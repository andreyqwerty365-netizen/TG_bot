import { render,screen } from '@testing-library/react';
import { expect,test,vi } from 'vitest';
import { OperationsPanel } from './operations';
import type { Api } from './api';

test('stale processing and unknown delivery are visible instead of a success indicator',async()=>{
  const api=vi.fn().mockResolvedValue({workers:{source:{status:'stale',last_seen_at:null,error_code:null},delivery:{status:'disabled'},backup:{status:'disabled'}},
    queue:{pending:3,failed:1,unknown:2},backup:{status:'disabled',last_verified_at:null}});
  render(<OperationsPanel api={api as Api} revision={0} zone="Europe/Moscow"/>);
  expect(await screen.findByText('Нет свежего сигнала')).toBeTruthy();
  expect(screen.getByText(/Неопределённый исход: 2/)).toBeTruthy();
  expect(api).toHaveBeenCalledWith('/workspace/system','GET',undefined,expect.any(AbortSignal));
});
