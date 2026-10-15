import importlib.util
from pathlib import Path

import pytest


def runner():
    spec=importlib.util.spec_from_file_location('browser_checks',Path('scripts/browser_checks.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('url',[
    'postgresql+psycopg://crm_test@127.0.0.1/personal_crm',
    'postgresql+psycopg://crm_test@127.0.0.1/personal_crm_test',
    'postgresql+psycopg://crm_test@db.example.invalid/personal_crm_test_web_ci_sample',
    'sqlite:///personal_crm_test_web_ci_sample',
])
def test_browser_runner_refuses_non_disposable_or_remote_database(url):
    with pytest.raises(ValueError,match='browser_database_required'):runner().guard_database(url)


def test_browser_runner_builds_isolated_disabled_environment():
    module=runner()
    env=module.environment({'PATH':'synthetic-path','CRM_MAIL_ENABLED':'true','OPENAI_API_KEY':'synthetic-secret',
        'CRM_WEB_PASSWORD_HASH':'old','CRM_OWNER_ID':'other-owner','BOT_TOKEN':'old-bot','PGPASSWORD':'old-password'},
        'postgresql+psycopg://crm_test@127.0.0.1/personal_crm_test_web_ci_sample','http://127.0.0.1:8119','synthetic-browser-ci')
    assert env['CRM_MAIL_ENABLED']==env['CRM_MAIL_READ_CONSENT']==env['CRM_OPENAI_ENABLED']=='false'
    assert env['CRM_TELEGRAM_SEND_ENABLED']==env['CRM_TELEGRAM_WEBHOOK_ENABLED']==env['CRM_BACKUP_ENABLED']=='false'
    assert 'OPENAI_API_KEY' not in env and 'BOT_TOKEN' not in env and 'PGPASSWORD' not in env
    assert env['CRM_OWNER_ID'].startswith('synthetic-') and env['CRM_WEB_INSECURE_LOCALHOST']=='true'
    assert env['CRM_WEB_TEST_BASE']=='http://127.0.0.1:8119/app/'
    from argon2 import PasswordHasher
    assert PasswordHasher().verify(env['CRM_WEB_PASSWORD_HASH'],env['CRM_WEB_TEST_TOKEN'])
