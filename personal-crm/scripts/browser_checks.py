"""Own a fresh synthetic browser laboratory on Linux or Windows; never reuse live services."""
import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request,urlopen

from argon2 import PasswordHasher
from sqlalchemy import make_url,text

ROOT=Path(__file__).resolve().parents[1]


def guard_database(url):
    try:
        value=make_url(url)
        if (value.drivername!='postgresql+psycopg' or value.host not in ('127.0.0.1','localhost','::1')
            or value.username!='crm_test' or not re.fullmatch(r'personal_crm_test_web_ci_[a-z0-9_]+',value.database or '')):
            raise ValueError()
    except Exception:
        raise ValueError('browser_database_required') from None


def environment(inherited,url,origin,password):
    guard_database(url)
    env={k:v for k,v in inherited.items() if not k.upper().startswith(('CRM_','OPENAI_','BOT_','PG'))}
    env.update(PYTHONUTF8='1',CRM_DATABASE_URL=url,CRM_OWNER_ID='synthetic-browser-ci',CRM_OWNER_TOKEN=password,
        CRM_ENVIRONMENT='development',CRM_WEB_ORIGIN=origin,CRM_WEB_INSECURE_LOCALHOST='true',
        CRM_WEB_PASSWORD_HASH=PasswordHasher().hash(password),CRM_TIMEZONE='Europe/Moscow',
        CRM_OPENAI_ENABLED='false',CRM_MAIL_ENABLED='false',CRM_MAIL_READ_CONSENT='false',
        CRM_TELEGRAM_SEND_ENABLED='false',CRM_TELEGRAM_WEBHOOK_ENABLED='false',CRM_BACKUP_ENABLED='false',
        CRM_S3_ENABLED='false',CRM_WEB_TEST_BASE=origin+'/app/',CRM_WEB_TEST_TOKEN=password)
    return env


def run(url):
    guard_database(url)
    from personal_crm.db import sessions
    factory=sessions(url)
    try:
        with factory() as s:
            if s.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")):
                raise ValueError('browser_database_must_be_empty')
    finally:factory.kw['bind'].dispose()
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:raise ValueError('npm_required')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    env=environment(os.environ,url,origin,'synthetic-'+secrets.token_urlsafe(24))
    runtime=ROOT/'.runtime'/('browser-ci-'+secrets.token_hex(6));runtime.mkdir(parents=True)
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,check=True)
    children=[];streams=[]
    try:
        for name,args in [('api',['-m','uvicorn','personal_crm.mail_demo:create_demo_app','--factory','--host','127.0.0.1',
                                 '--port',str(port),'--no-access-log']),('source',['-m','personal_crm.source_worker'])]:
            stream=(runtime/(name+'.log')).open('wb');streams.append(stream)
            children.append(subprocess.Popen([sys.executable,*args],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT))
        deadline=time.monotonic()+60
        while True:
            if any(child.poll() is not None for child in children):raise RuntimeError('browser_service_exited')
            try:
                request=Request(origin+'/workspace/system',headers={'Authorization':'Bearer '+env['CRM_OWNER_TOKEN']})
                with urlopen(request,timeout=2) as response:status=json.load(response)
                if status['workers']['source']['status'] in ('running','idle'):break
            except (URLError,TimeoutError,ConnectionError):pass
            if time.monotonic()>deadline:raise RuntimeError('browser_service_timeout')
            time.sleep(.25)
        subprocess.run([npm,'run','test:e2e'],cwd=ROOT/'web',env=env,check=True)
        print(json.dumps({'status':'browser_checks_passed','laboratory':'new synthetic database and owned child processes'}))
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate()
        for child in reversed(children):
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        for stream in streams:stream.close()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:run(os.environ.get('CRM_BROWSER_DATABASE_URL',''))
    except Exception:raise SystemExit('browser_checks_failed; inspect only the synthetic .runtime/browser-ci-* logs') from None


if __name__=='__main__':main()
