import { afterEach, expect, test, vi } from 'vitest';
import { makeSessionApi } from './api';

afterEach(()=>vi.unstubAllGlobals());

test('an HTML gateway error gives a safe retry message instead of a JSON parser error',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('<html>private gateway diagnostic</html>',{status:502})));
  await expect(makeSessionApi('synthetic-csrf')('/workspace/tasks','POST',{title:'Учебное дело'}))
    .rejects.toThrow('Сервер временно недоступен. Повторите попытку; результат сохранения пока неизвестен.');
});

test('an incomplete success response does not claim that a write failed or succeeded',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{', {status:200})));
  await expect(makeSessionApi('synthetic-csrf')('/workspace/tasks','POST',{title:'Учебное дело'}))
    .rejects.toThrow('Ответ сервера не удалось прочитать. Повторите попытку; результат сохранения пока неизвестен.');
});

test('an unreadable unauthorized response still expires the session',async()=>{
  const expired=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('',{status:401})));
  await expect(makeSessionApi('synthetic-csrf',expired)('/overview')).rejects.toThrow();
  expect(expired).toHaveBeenCalledOnce();
});
