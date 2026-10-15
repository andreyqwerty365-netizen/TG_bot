from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.models import SourceVersion, Task
from test_stage2_offline import OWNER, ru_service

AUTH = {'Authorization':'Bearer synthetic-capture-secret'}


def web(factory, ru_service, clock):
    app = create_app(Settings(factory.kw['bind'].url.render_as_string(hide_password=False),OWNER,
                              'synthetic-capture-secret',timezone='Europe/Moscow'),ru_service.interpreter)
    app.state.service.clock = clock
    return TestClient(app)


def test_capture_saves_free_text_and_short_answer_without_another_task(factory, ru_service, clock):
    client = web(factory,ru_service,clock)
    result = client.post('/workspace/capture',headers=AUTH,json={'request_id':'capture-1','text':'Завтра напомни обновить резюме'})
    assert result.status_code == 200
    data = result.json()
    assert data['result']['status'] == 'clarification'
    assert data['source_version_id']
    result = client.post(f"/workspace/sources/{data['source_version_id']}/reply",headers=AUTH,
                        json={'request_id':'answer-1','text':'в 19:00'})
    assert result.status_code == 200 and result.json()['status'] == 'created'
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 1


def test_capture_retry_preserves_source_id_and_conflicting_payload_is_rejected(factory, ru_service, clock):
    client = web(factory,ru_service,clock)
    body = {'request_id':'capture-repeat','text':'Завтра в 19:00 напомни обновить резюме'}
    first = client.post('/workspace/capture',headers=AUTH,json=body)
    assert first.status_code == 200
    assert first.json()['result']['status'] == 'created'
    second = client.post('/workspace/capture',headers=AUTH,json=body)
    assert second.json() == first.json()
    assert client.post('/workspace/capture',headers=AUTH,json={**body,'text':'Другой текст'}).status_code == 409
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(SourceVersion)) == 1
        assert s.scalar(select(func.count()).select_from(Task)) == 1
    assert client.post('/workspace/capture',json=body).status_code == 401


def test_capture_two_requests_commit_only_one_result(factory, ru_service, clock):
    def submit(_):
        return web(factory,ru_service,clock).post('/workspace/capture',headers=AUTH,
            json={'request_id':'capture-concurrent','text':'Завтра в 19:00 напомни обновить резюме'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit,range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json()['source_version_id'] == responses[1].json()['source_version_id']
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Task)) == 1
