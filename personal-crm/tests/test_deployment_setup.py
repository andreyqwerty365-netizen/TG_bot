"""Only synthetic configuration; never discover or load an existing operator .env."""
import base64
import importlib
import json
import os
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy.engine import make_url


def test_operator_setup_command_is_available():
    assert importlib.util.find_spec('personal_crm.deployment_setup') is not None


@pytest.fixture
def setup_tool():
    try:
        return importlib.import_module('personal_crm.deployment_setup')
    except ModuleNotFoundError:
        pytest.fail('deployment configuration generator is not implemented')


@pytest.fixture
def options(tmp_path, setup_tool, monkeypatch):
    monkeypatch.setattr(setup_tool, 'REPOSITORY', tmp_path/'checkout')
    return dict(directory=tmp_path/'private-config', host='crm.example.org',
                email='operator@example.org', image='sha256:'+'a'*64,
                backup_image='sha256:'+'b'*64, password='synthetic operator password')


def values(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#'))


def test_configuration_has_matching_generated_credentials_and_private_files(setup_tool, options):
    result=setup_tool.generate(**options)
    directory=options['directory']
    assert result['status']=='configuration_created'
    assert len(list(directory.iterdir()))==8
    database=make_url(values(directory/'database.env')['CRM_DATABASE_URL'])
    assert database.password==(directory/'db-password').read_text().strip()
    assert database.host=='db' and database.database=='personal_crm'
    web=values(directory/'web.env')
    assert PasswordHasher().verify(web['CRM_WEB_PASSWORD_HASH'], options['password'])
    assert web['CRM_WEB_ORIGIN']=='https://crm.example.org'
    backup=values(directory/'backup.env')
    assert len(base64.urlsafe_b64decode(backup['CRM_BACKUP_KEY']))==32
    assert backup['CRM_S3_ENABLED']==backup['CRM_BACKUP_ENABLED']=='false'
    assert values(directory/'ingress.env')['CRM_TELEGRAM_WEBHOOK_ENABLED']=='false'
    assert values(directory/'delivery.env')['CRM_TELEGRAM_SEND_ENABLED']=='false'
    if os.name!='nt':
        assert directory.stat().st_mode & 0o777==0o700
        assert all(p.stat().st_mode & 0o777==0o600 for p in directory.iterdir())
    assert options['password'] not in ''.join(p.read_text() for p in directory.iterdir())
    assert 'password' not in json.dumps(result)


def test_repeat_never_rotates_existing_database_or_backup_credentials(setup_tool, options):
    setup_tool.generate(**options)
    before={p.name:p.read_bytes() for p in options['directory'].iterdir()}
    with pytest.raises(ValueError, match='configuration_directory_exists'):
        setup_tool.generate(**options)
    assert before=={p.name:p.read_bytes() for p in options['directory'].iterdir()}


@pytest.mark.parametrize('field,value', [
    ('host','https://crm.example.org'), ('host','crm.example.org\nCRM_MAIL_ENABLED=true'),
    ('host','127.0.0.1'), ('host','localhost'), ('host','*.example.org'),
    ('email','operator@example.org\nINJECT=true'), ('image','personal-crm:latest'),
    ('backup_image','sha256:abc'), ('password','too short'),
])
def test_invalid_input_creates_no_directory(setup_tool, options, field, value):
    options[field]=value
    with pytest.raises(ValueError):setup_tool.generate(**options)
    assert not options['directory'].exists()


def test_checkout_and_symlink_paths_are_refused(setup_tool, options, tmp_path):
    checkout=tmp_path/'checkout';checkout.mkdir()
    options['directory']=checkout/'private'
    with pytest.raises(ValueError,match='configuration_outside_checkout_required'):
        setup_tool.generate(**options)
    if os.name!='nt':
        link=tmp_path/'link';link.symlink_to(checkout,target_is_directory=True)
        options['directory']=link/'private'
        with pytest.raises(ValueError):setup_tool.generate(**options)
        assert not (checkout/'private').exists()


def test_offline_check_reports_pending_external_acceptance_without_secrets(setup_tool, options, monkeypatch):
    setup_tool.generate(**options)
    monkeypatch.setenv('CRM_MAIL_ENABLED','true')
    monkeypatch.setenv('CRM_DATABASE_URL','this-inherited-value-must-never-be-used')
    report=setup_tool.check(options['directory'])
    assert report['status']=='configuration_valid'
    assert report['integrations']=={'telegram':'disabled','backup':'disabled','mail':'disabled','ai':'disabled'}
    assert 'public_https' in report['not_checked'] and 'remote_restore' in report['not_checked']
    text=json.dumps(report)
    assert all(secret not in text for secret in [options['password'],'crm.example.org',
        values(options['directory']/'backup.env')['CRM_BACKUP_KEY'],
        (options['directory']/'db-password').read_text().strip()])


@pytest.mark.parametrize('file,append', [
    ('database.env','CRM_DATABASE_URL=postgresql+psycopg://crm:wrong@db:5432/personal_crm\n'),
    ('web.env','CRM_WEB_ORIGIN=https://other.example.org\n'),
    ('web.env','CRM_BACKUP_ENABLED=true\n'),
    ('web.env','CRM_MAIL_ENABLED=true\n'),
    ('identity.env','CRM_TIMEZONE=Unknown/Nowhere\n'),
])
def test_check_rejects_duplicate_unknown_and_inconsistent_values(setup_tool, options, file, append):
    setup_tool.generate(**options)
    path=options['directory']/file
    with path.open('a') as stream:stream.write(append)
    with pytest.raises(ValueError):setup_tool.check(options['directory'])


@pytest.mark.parametrize('file,key,replacement,code',[
    ('web.env','CRM_WEB_ORIGIN','https://other.example.org','web_origin_mismatch'),
    ('web.env','CRM_BACKUP_ENABLED','true','integration_flags_mismatch'),
    ('identity.env','CRM_TIMEZONE','Unknown/Nowhere','timezone_invalid'),
    ('web.env','CRM_WEB_PASSWORD_HASH','synthetic-not-an-argon-hash','password_hash_invalid'),
    ('backup.env','CRM_BACKUP_KEY','invalid','backup_key_invalid'),
])
def test_check_validates_edited_values_without_duplicate_keys(setup_tool, options, file, key, replacement, code):
    setup_tool.generate(**options)
    path=options['directory']/file
    data=values(path);data[key]=replacement
    path.write_text(''.join(k+'='+v+'\n' for k,v in data.items()))
    with pytest.raises(ValueError,match=code):setup_tool.check(options['directory'])


def test_check_rejects_changed_password_and_enabled_unconfigured_integrations(setup_tool, options):
    setup_tool.generate(**options)
    directory=options['directory']
    (directory/'db-password').write_text('another-synthetic-password\n')
    with pytest.raises(ValueError,match='database_credentials_mismatch'):setup_tool.check(directory)
    (directory/'db-password').write_text(make_url(values(directory/'database.env')['CRM_DATABASE_URL']).password+'\n')
    for file in ['web.env','delivery.env']:
        path=directory/file
        path.write_text(path.read_text().replace('CRM_TELEGRAM_SEND_ENABLED=false','CRM_TELEGRAM_SEND_ENABLED=true'))
    with pytest.raises(ValueError,match='telegram_configuration_invalid'):setup_tool.check(directory)


@pytest.mark.skipif(os.name=='nt',reason='POSIX permission check is exercised on Linux CI')
def test_check_rejects_readable_or_linked_secret_files(setup_tool, options, tmp_path):
    setup_tool.generate(**options)
    path=options['directory']/'backup.env'
    path.chmod(0o644)
    with pytest.raises(ValueError,match='private_permissions_required'):setup_tool.check(options['directory'])
    path.chmod(0o600);original=tmp_path/'elsewhere';path.rename(original);path.symlink_to(original)
    with pytest.raises(ValueError,match='regular_private_file_required'):setup_tool.check(options['directory'])


def test_cli_prints_only_safe_error_and_takes_password_privately(setup_tool, options, monkeypatch, capsys):
    answers=iter(['synthetic operator password']*2)
    monkeypatch.setattr('getpass.getpass',lambda _:next(answers))
    monkeypatch.setattr(setup_tool,'require_linux',lambda:None)
    monkeypatch.setattr('sys.stdin.isatty',lambda:True)
    args=['generate','--directory',str(options['directory']),'--host',options['host'],
          '--email',options['email'],'--image',options['image'],'--backup-image',options['backup_image']]
    assert setup_tool.main(args)==0
    output=capsys.readouterr()
    assert json.loads(output.out)['status']=='configuration_created' and output.err==''
    assert setup_tool.main(['check','--directory',str(options['directory'])])==0
    output=capsys.readouterr()
    assert json.loads(output.out)['status']=='configuration_valid'
    with (options['directory']/'database.env').open('a') as stream:stream.write('SECRET=synthetic-private-value\n')
    assert setup_tool.main(['check','--directory',str(options['directory'])])==1
    output=capsys.readouterr()
    assert 'synthetic-private-value' not in output.out+output.err
    assert 'configuration_invalid' in output.err


def test_cli_hides_malformed_database_url(setup_tool, options, monkeypatch, capsys):
    setup_tool.generate(**options)
    (options['directory']/'database.env').write_text('CRM_DATABASE_URL=synthetic-private-url\n')
    monkeypatch.setattr(setup_tool,'require_linux',lambda:None)
    assert setup_tool.main(['check','--directory',str(options['directory'])])==1
    output=capsys.readouterr()
    assert 'synthetic-private-url' not in output.out+output.err


def test_optional_integration_configuration_is_unverified_until_external_rehearsal(setup_tool, options):
    setup_tool.generate(**options)
    directory=options['directory']
    def update(file,changes):
        data=values(directory/file);data.update(changes)
        (directory/file).write_text(''.join(k+'='+v+'\n' for k,v in data.items()))
    update('web.env',{'CRM_TELEGRAM_SEND_ENABLED':'true','CRM_BACKUP_ENABLED':'true','CRM_S3_ENABLED':'true'})
    common={'CRM_TELEGRAM_BOT_ID':'123456789','CRM_TELEGRAM_ALLOWED_USER_IDS':'123456789',
            'CRM_TELEGRAM_ALLOWED_CHAT_IDS':'123456789'}
    update('delivery.env',{**common,'CRM_TELEGRAM_SEND_ENABLED':'true','CRM_TELEGRAM_OUTBOUND_CHAT_ID':'123456789',
                           'CRM_TELEGRAM_TEST_TOKEN':'123456789:'+'synthetic_token_'*3})
    update('ingress.env',{**common,'CRM_TELEGRAM_WEBHOOK_ENABLED':'true','CRM_TELEGRAM_WEBHOOK_SECRET':'synthetic_'*4})
    update('backup.env',{'CRM_BACKUP_ENABLED':'true','CRM_S3_ENABLED':'true','CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED':'true',
        'CRM_S3_ENDPOINT':'https://s3.example.org','CRM_S3_BUCKET':'synthetic-bucket',
        'CRM_S3_ACCESS_KEY':'synthetic-access','CRM_S3_SECRET_KEY':'synthetic-secret'})
    before={p.name:p.read_bytes() for p in directory.iterdir()}
    report=setup_tool.check(directory)
    assert report['integrations']['telegram']==report['integrations']['backup']=='configured_unverified'
    assert before=={p.name:p.read_bytes() for p in directory.iterdir()}
    update('ingress.env',{'CRM_TELEGRAM_ALLOWED_USER_IDS':'987654321'})
    with pytest.raises(ValueError,match='telegram_identity_mismatch'):setup_tool.check(directory)


def test_piped_password_is_refused_before_any_file_is_written(setup_tool, options, monkeypatch, capsys):
    monkeypatch.setattr(setup_tool,'require_linux',lambda:None)
    monkeypatch.setattr('sys.stdin.isatty',lambda:False)
    monkeypatch.setattr('getpass.getpass',lambda _:pytest.fail('password must not be read from a pipe'))
    assert setup_tool.main(['generate','--directory',str(options['directory']),'--host',options['host'],
        '--email',options['email'],'--image',options['image'],'--backup-image',options['backup_image']])==1
    assert not options['directory'].exists()
