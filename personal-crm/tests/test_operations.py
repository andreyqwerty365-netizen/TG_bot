import importlib
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from personal_crm.api import create_app
from personal_crm.auth_config import WebAuthConfig
from personal_crm.config import Settings
from personal_crm.models import Job
from test_web_sessions import HASH,ORIGIN


def test_heartbeat_and_queue_status_distinguish_stale_disabled_and_failure(factory,service,clock):
    ops=importlib.import_module('personal_crm.operations')
    ops.record(factory,'synthetic-owner','source','running',now=clock.now)
    with factory.begin() as s:
        s.add(Job(owner_id='synthetic-owner',kind='digest',dedupe_key='ops-due',run_at=clock.now-timedelta(minutes=2)))
    view=ops.overview(factory,'synthetic-owner',now=clock.now,delivery_enabled=False,backup_enabled=False)
    assert view['workers']['source']['status']=='running'
    assert view['workers']['delivery']['status']=='disabled'
    assert view['queue']['pending']==1
    assert view['queue']['oldest_pending_at']
    clock.now+=timedelta(seconds=91)
    assert ops.overview(factory,'synthetic-owner',now=clock.now)['workers']['source']['status']=='stale'
    ops.record(factory,'synthetic-owner','source','error',error_code='source_unavailable',now=clock.now)
    assert ops.overview(factory,'synthetic-owner',now=clock.now)['workers']['source']['status']=='error'
    with pytest.raises(ValueError):
        ops.record(factory,'synthetic-owner','source','error',error_code='private synthetic text',now=clock.now)


def test_production_ready_requires_actual_source_heartbeat_and_status_is_owner_only(factory,service,clock):
    ops=importlib.import_module('personal_crm.operations')
    settings=Settings(factory.kw['bind'].url.render_as_string(hide_password=False),'synthetic-owner','synthetic-ops',
                      timezone='Europe/Berlin',web_auth=WebAuthConfig(HASH,ORIGIN),environment='production')
    app=create_app(settings)
    app.state.service.clock=clock
    client=TestClient(app,base_url=ORIGIN)
    assert client.get('/ready').status_code==503
    ops.record(factory,'synthetic-owner','source','running',now=clock.now)
    response=client.get('/ready')
    assert response.status_code==200 and 'fake' not in response.text
    assert client.get('/workspace/system').status_code==401
    result=client.get('/workspace/system',headers={'Authorization':'Bearer synthetic-ops'})
    assert result.status_code==200
    assert 'synthetic-ops' not in result.text
    clock.now+=timedelta(seconds=91)
    assert client.get('/ready').status_code==503


def test_backup_success_is_visible_and_expires_after_26_hours(factory,service,clock):
    ops=importlib.import_module('personal_crm.operations')
    ops.record(factory,'synthetic-owner','backup','running',success_at=clock.now,now=clock.now)
    view=ops.overview(factory,'synthetic-owner',now=clock.now,backup_enabled=True)
    assert view['backup']['status']=='verified'
    clock.now+=timedelta(hours=26,seconds=1)
    assert ops.overview(factory,'synthetic-owner',now=clock.now,backup_enabled=True)['backup']['status']=='overdue'
    service.register('synthetic-other','UTC')
    assert ops.overview(factory,'synthetic-other',now=clock.now,backup_enabled=True)['backup']['status']=='missing'
