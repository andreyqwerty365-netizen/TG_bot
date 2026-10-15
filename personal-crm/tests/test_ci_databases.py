import importlib.util
from pathlib import Path
import pytest


def helper():
    spec=importlib.util.spec_from_file_location('ci_databases',Path('scripts/ci_databases.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('url',[
    'postgresql+psycopg://postgres@127.0.0.1/postgres',
    'postgresql+psycopg://crm_test@db.example.invalid/postgres',
    'postgresql+psycopg://crm_test@127.0.0.1/personal_crm',
    'sqlite:///postgres',
])
def test_ci_database_creation_requires_explicit_local_test_role(url):
    with pytest.raises(ValueError,match='local_test_admin_required'):helper().plan(url,'abc123')


def test_ci_database_names_are_distinct_disposable_and_bounded():
    result=helper().plan('postgresql+psycopg://crm_test@127.0.0.1/postgres','abc123')
    assert result=={'CRM_TEST_DATABASE_URL':'postgresql+psycopg://crm_test@127.0.0.1/personal_crm_test_ci_abc123',
        'CRM_BROWSER_DATABASE_URL':'postgresql+psycopg://crm_test@127.0.0.1/personal_crm_test_web_ci_abc123',
        'CRM_LOAD_DATABASE_URL':'postgresql+psycopg://crm_test@127.0.0.1/personal_crm_test_load_ci_abc123'}
    with pytest.raises(ValueError):helper().plan('postgresql+psycopg://crm_test@127.0.0.1/postgres','bad/name')
