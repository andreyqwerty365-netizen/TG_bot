"""Synthetic, non-destructive ASGI/PostgreSQL load rehearsal; not a VPS capacity claim."""
import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import insert,make_url,select,text

from .api import create_app
from .config import Settings
from .db import sessions
from .models import Job,Profile,Source,SourceVersion,Task,uid

OWNER='synthetic-load-owner'
TOKEN='synthetic-load-token'


def conditions():
    return f'{platform.system()} local PostgreSQL, in-process ASGI; excludes HTTP/TLS and VPS capacity'


def guard(url):
    value=make_url(url)
    if value.drivername!='postgresql+psycopg' or not re.fullmatch(r'personal_crm_test_load_[a-z0-9_]+',value.database or ''):
        raise ValueError('dedicated_empty_load_database_required')


def run(url):
    guard(url);factory=sessions(url)
    with factory() as s:
        server_version=s.scalar(text('SHOW server_version'))
        if s.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")):
            raise ValueError('dedicated_empty_load_database_required')
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True,
                   env={**os.environ,'CRM_DATABASE_URL':url})
    now=datetime.now(UTC);count=10000
    with factory.begin() as s:
        s.add(Profile(id=OWNER,timezone='Europe/Moscow',digest_hour=9));s.flush()
        for offset in range(0,count,500):
            sources=[];versions=[];tasks=[]
            for index in range(offset,offset+500):
                source_id,version_id,task_id=uid(),uid(),uid();title=f'Synthetic load task {index:05d}'
                sources.append(dict(id=source_id,owner_id=OWNER,channel='owner',account='load',external_id=str(index)))
                versions.append(dict(id=version_id,source_id=source_id,revision=1,text=title,status='processed',received_at=now))
                tasks.append(dict(id=task_id,owner_id=OWNER,source_version_id=version_id,title=title,title_search=title.casefold(),
                                  planned_on=now.date() if index%100==0 else None))
            s.execute(insert(Source),sources);s.execute(insert(SourceVersion),versions);s.execute(insert(Task),tasks)
        s.add(Job(owner_id=OWNER,kind='digest',dedupe_key='load-restart-evidence',run_at=now))
    config=Settings(url,OWNER,TOKEN,timezone='Europe/Moscow')
    app=create_app(config);timings={'search':[],'today':[],'create':[]}
    def client_work(index):
        result={key:[] for key in timings}
        with TestClient(app) as client:
            headers={'Authorization':'Bearer '+TOKEN}
            for n in range(10):
                for name,path in [('search','/workspace/tasks?q=009&limit=30'),('today','/overview')]:
                    started=time.perf_counter();response=client.get(path,headers=headers)
                    response.raise_for_status();result[name].append(time.perf_counter()-started)
                started=time.perf_counter()
                client.post('/workspace/tasks',headers=headers,json={'request_id':f'load-{index}-{n}',
                    'title':f'Synthetic parallel saved {index}-{n}'}).raise_for_status()
                result['create'].append(time.perf_counter()-started)
        return result
    with ThreadPoolExecutor(max_workers=10) as pool:
        for result in pool.map(client_work,range(10)):
            for key in timings:timings[key].extend(result[key])
    restarted=create_app(config)
    with TestClient(restarted) as client:
        response=client.get('/workspace/tasks',headers={'Authorization':'Bearer '+TOKEN});response.raise_for_status()
        assert response.json()['total']==10100
    with factory() as s:
        assert s.scalar(select(Job.status).where(Job.dedupe_key=='load-restart-evidence'))=='pending'
    factory.kw['bind'].dispose()
    stats={key:{'requests':len(values),'p95_seconds':round(sorted(values)[math.ceil(len(values)*.95)-1],4),
                'max_seconds':round(max(values),4)} for key,values in timings.items()}
    return {'status':'measured','seed_tasks':count,'clients':10,'measurements':stats,'restart':'persisted_without_delivery',
            'conditions':conditions(),'postgresql_version':server_version,
            'targets_met':all(stats[key]['p95_seconds']<limit for key,limit in [('search',1),('today',1),('create',2)])}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    report=run(os.getenv('CRM_LOAD_DATABASE_URL',''))
    args.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report['targets_met']:raise SystemExit(1)


if __name__=='__main__':main()
