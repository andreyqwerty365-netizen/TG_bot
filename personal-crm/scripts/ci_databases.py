"""Create NEW, separate synthetic databases; never reset an existing database."""
import argparse
import os
import re
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import make_url

ROOT=Path(__file__).resolve().parents[1]


def plan(url,suffix):
    try:
        source=make_url(url)
        if (source.drivername!='postgresql+psycopg' or source.database!='postgres' or source.username!='crm_test'
            or source.host not in ('127.0.0.1','localhost','::1') or not re.fullmatch(r'[a-f0-9]{6,16}',suffix)):
            raise ValueError()
    except Exception:raise ValueError('local_test_admin_required') from None
    return {key:source.set(database=prefix+suffix).render_as_string(hide_password=False) for key,prefix in [
        ('CRM_TEST_DATABASE_URL','personal_crm_test_ci_'),('CRM_BROWSER_DATABASE_URL','personal_crm_test_web_ci_'),
        ('CRM_LOAD_DATABASE_URL','personal_crm_test_load_ci_')]}


def create(url,destination):
    planned=plan(url,secrets.token_hex(6));destination=Path(destination).resolve()
    runtime=(ROOT/'.runtime').resolve()
    if not destination.is_relative_to(runtime) or destination.exists():raise ValueError('new_private_runtime_file_required')
    destination.parent.mkdir(parents=True,exist_ok=True)
    source=make_url(url);created=[]
    with psycopg.connect(host=source.host,port=source.port,user=source.username,password=source.password,
                         dbname='postgres',connect_timeout=5,autocommit=True) as conn:
        try:
            for value in planned.values():
                name=make_url(value).database
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
                created.append(name)
            descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                stream.write(''.join(key+'='+value+'\n' for key,value in planned.items()))
        except Exception:
            for name in reversed(created):
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
            raise
    return {'status':'three_new_synthetic_databases_created'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:print(create(os.environ.get('CRM_CI_ADMIN_URL',''),args.output)['status'])
    except Exception:raise SystemExit('ci_database_setup_failed') from None


if __name__=='__main__':main()
