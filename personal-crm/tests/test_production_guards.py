import os
import subprocess
import sys
from dataclasses import replace

import pytest
from sqlalchemy import select

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.models import Attempt, Job


def test_production_disabled_transport_cannot_consume_pending_jobs(factory, service, clock):
    with factory.begin() as s:
        s.add(Job(owner_id='synthetic-owner',kind='digest',dedupe_key='prod-guard',run_at=clock.now))
    result = subprocess.run([sys.executable,'-m','personal_crm.worker','--once'],capture_output=True,text=True,timeout=20,
                            env={**os.environ,'CRM_ENVIRONMENT':'production','CRM_TELEGRAM_SEND_ENABLED':'false',
                                 'CRM_OWNER_ID':'synthetic-owner','CRM_DATABASE_URL':factory.kw['bind'].url.render_as_string(hide_password=False)})
    assert result.returncode == 0
    assert 'disabled' in result.stdout
    with factory() as s:
        assert s.scalar(select(Job.status)) == 'pending'
        assert s.scalar(select(Attempt.id)) is None


def test_internal_source_worker_does_not_require_browser_bearer(factory,service):
    result=subprocess.run([sys.executable,'-m','personal_crm.source_worker','--once'],capture_output=True,text=True,timeout=20,
        env={**os.environ,'CRM_ENVIRONMENT':'production','CRM_OWNER_ID':'synthetic-owner','CRM_OWNER_TOKEN':'',
             'CRM_OPENAI_ENABLED':'false','CRM_DATABASE_URL':factory.kw['bind'].url.render_as_string(hide_password=False)})
    assert result.returncode==0


def test_synthetic_worker_heartbeat_follows_explicit_owner(factory,service):
    result=subprocess.run([sys.executable,'-m','personal_crm.worker','--once','--no-digest','--owner','synthetic-owner'],
        capture_output=True,text=True,timeout=20,env={**os.environ,'CRM_ENVIRONMENT':'development',
        'CRM_OWNER_ID':'synthetic-nonexistent-owner','CRM_TELEGRAM_SEND_ENABLED':'false',
        'CRM_DATABASE_URL':factory.kw['bind'].url.render_as_string(hide_password=False)})
    assert result.returncode==0 and 'database_unavailable' not in result.stdout


def test_production_requires_real_web_configuration(factory):
    settings = Settings(factory.kw['bind'].url.render_as_string(hide_password=False),'synthetic-owner','synthetic-bearer',environment='production')
    with pytest.raises(ValueError,match='production_web_auth_required'):
        create_app(settings)


@pytest.mark.parametrize('origin',['https://crm.example/path','https://user:secret@crm.example','https://crm.example?token=private'])
def test_production_rejects_invalid_origin_before_startup(factory,origin):
    from argon2 import PasswordHasher
    from personal_crm.auth_config import WebAuthConfig
    settings=Settings(factory.kw['bind'].url.render_as_string(hide_password=False),'synthetic-owner',
        web_auth=WebAuthConfig(PasswordHasher().hash('synthetic'),origin),environment='production')
    with pytest.raises(ValueError,match='production_web_auth_required'):create_app(settings)
