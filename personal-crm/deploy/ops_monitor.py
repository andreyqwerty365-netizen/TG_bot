"""Bounded host-only probes and quiet transition alerts. No task payloads in reports."""
import argparse
import copy
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

LABELS={'https':'HTTPS CRM','containers':'процессы CRM и бота','source':'обработка сообщений',
        'crm_backup':'копия PostgreSQL','legacy_backup':'копии SQLite бота','restore':'проверка восстановления',
        'disk':'свободное место','backup_timer':'таймер копий бота'}
CONTAINERS=('personal-crm-pilot-api-1','personal-crm-pilot-source-1','personal-crm-pilot-db-1',
            'personal-crm-pilot-caddy-1','personal-crm-pilot-backup-1','legacy-reminder-bot-bot-1')


def is_recent(value,now,seconds):
    try:
        stamp=datetime.fromisoformat(value)
        return stamp.tzinfo is not None and -timedelta(seconds=60)<=now-stamp<=timedelta(seconds=seconds)
    except (TypeError,ValueError):
        return False


def transition(state,checks,notify):
    if set(checks)-LABELS.keys():raise ValueError('unknown_probe')
    state=copy.deepcopy(state)
    failed=[];recovered=[]
    for name,ok in checks.items():
        item=state.setdefault(name,{'bad':0,'good':0,'alerted':False})
        item['bad']=0 if ok else min(2,item['bad']+1)
        item['good']=min(2,item['good']+1) if ok else 0
        if item['bad']>=2 and not item['alerted']:
            failed.append(name)
        elif item['good']>=2 and item['alerted']:
            recovered.append(name)
    messages=[]
    if failed:messages.append('Сбой: '+', '.join(LABELS[name] for name in failed)+'. Требуется проверка.')
    if recovered:messages.append('Восстановлено: '+', '.join(LABELS[name] for name in recovered)+'. Проверки снова проходят.')
    if messages:
        notify('\n'.join(messages))
        for name in failed:state[name]['alerted']=True
        for name in recovered:state[name]['alerted']=False
    return state


def heartbeat_url(value):
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or parsed.hostname!='hc-ping.com' or parsed.netloc!='hc-ping.com'
            or parsed.query or parsed.fragment or not re.fullmatch(r'/[a-f0-9-]{36}',parsed.path)):
        raise ValueError('heartbeat_url_invalid')
    return value


def request(host,path,*,body=None,ipv6=False):
    connection=http.client.HTTPSConnection(host,timeout=8,context=ssl.create_default_context())
    if ipv6:
        # Only this approved Telegram connection uses the VPS's verified IPv6 route.
        def connect(address,timeout=8,source_address=None):
            last=None
            for family,kind,proto,_,target in socket.getaddrinfo(address[0],address[1],socket.AF_INET6,socket.SOCK_STREAM):
                sock=socket.socket(family,kind,proto);sock.settimeout(timeout)
                try:sock.connect(target);return sock
                except OSError as error:last=error;sock.close()
            raise OSError('ipv6_connection_failed') from last
        connection._create_connection=connect
    try:
        encoded=None if body is None else json.dumps(body).encode()
        connection.request('GET' if body is None else 'POST',path,body=encoded,
                           headers={} if body is None else {'Content-Type':'application/json'})
        response=connection.getresponse();value=response.read(16385)
        if response.status!=200 or len(value)>16384:raise OSError('remote_response_failed')
        return value
    finally:connection.close()


def telegram(config,message):
    token=config['telegram_bot_token'];chat=config['telegram_chat_id']
    if not re.fullmatch(r'[0-9]{6,12}:[A-Za-z0-9_-]{30,80}',token) or not re.fullmatch(r'[1-9][0-9]{0,15}',str(chat)):
        raise ValueError('notification_configuration_invalid')
    result=json.loads(request('api.telegram.org','/bot'+token+'/sendMessage',
                             body={'chat_id':str(chat),'text':message,'disable_web_page_preview':True},ipv6=True))
    if result.get('ok') is not True:raise OSError('notification_failed')


def ping(url,failed=False):
    parsed=urlsplit(heartbeat_url(url))
    request(parsed.hostname,parsed.path+('/fail' if failed else ''))


def command(args):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15,check=True)
    if len(result.stdout)>65536:raise ValueError('probe_output_limit')
    return result.stdout.strip()


def load_json(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>65536:raise ValueError('state_invalid')
    return json.loads(path.read_text())


def write_json(path,value):
    path=Path(path);temp=path.with_name('.'+uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf8') as stream:
            os.chmod(temp,0o600);json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def collect(config,now):
    checks={}
    def check(name,call):
        try:checks[name]=bool(call())
        except Exception:checks[name]=False
    origin=urlsplit(config['crm_origin'])
    if origin.scheme!='https' or not origin.hostname or origin.netloc!=origin.hostname or origin.path not in ('','/'):
        raise ValueError('crm_origin_invalid')
    check('https',lambda:json.loads(request(origin.hostname,'/ready'))=={'status':'ready'})
    def containers():
        for name in CONTAINERS:
            value=command(['/usr/bin/docker','inspect','--format','{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{end}}',name]).split()
            if not value or value[0]!='true' or len(value)>1 and value[1]!='healthy':return False
        return True
    check('containers',containers)
    try:
        query="SELECT json_build_object('source_seen',(SELECT max(last_seen_at) FROM worker_status WHERE role='source'),'source_state',(SELECT state FROM worker_status WHERE role='source' ORDER BY last_seen_at DESC LIMIT 1),'backup_at',(SELECT max(last_success_at) FROM worker_status WHERE role='backup'),'backup_state',(SELECT state FROM worker_status WHERE role='backup' ORDER BY last_seen_at DESC LIMIT 1))"
        database=json.loads(command(['/usr/bin/docker','exec','personal-crm-pilot-db-1','psql','-X','-U','crm','-d','personal_crm','-Atc',query]))
        checks['source']=is_recent(database.get('source_seen'),now,180) and database.get('source_state') in ('idle','running')
        checks['crm_backup']=is_recent(database.get('backup_at'),now,26*3600) and database.get('backup_state') in ('idle','running')
    except Exception:checks.update(source=False,crm_backup=False)
    def legacy_backup():
        report=load_json(config['legacy_backup_report'])
        return report.get('status')=='verified_remote' and is_recent(report.get('created_at'),now,26*3600)
    check('legacy_backup',legacy_backup)
    def restore():
        last=load_json(config['restore_report'])
        success=load_json(str(Path(config['restore_report']).with_name('restore-last-success.json')))
        return last['status']=='verified' and is_recent(success['completed_at'],now,8*86400)
    check('restore',restore)
    check('disk',lambda:shutil.disk_usage('/srv').free>=3*1024**3 and shutil.disk_usage('/srv').free/shutil.disk_usage('/srv').total>=.10)
    check('backup_timer',lambda:command(['/usr/bin/systemctl','is-active','legacy-data-backup.timer'])=='active'
          and command(['/usr/bin/systemctl','show','legacy-data-backup.service','--value','-p','Result'])=='success')
    return checks


def main():
    import fcntl  # Linux-only locking; pure policy tests also run on Windows.
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('/etc/personal-crm/monitoring/monitor.json'))
    parser.add_argument('--test-message',action='store_true')
    args=parser.parse_args()
    try:
        config=load_json(args.config)
        if args.test_message:
            telegram(config,'Технический мониторинг CRM: проверка доставки. Это тест, рабочие сервисы не отключались.')
            print('notification_delivered');return 0
        directory=Path(config['state_directory']);directory.mkdir(mode=0o700,exist_ok=True)
        with (directory/'monitor.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            state_path=directory/'monitor-state.json'
            state=load_json(state_path) if state_path.exists() else {}
            now=datetime.now(UTC);checks=collect(config,now)
            state=transition(state,checks,lambda message:telegram(config,message))
            write_json(state_path,state)
            if config.get('heartbeat_url'):
                ping(config['heartbeat_url'],failed=any(item['bad']>=2 for item in state.values()))
            write_json(directory/'monitor-last-run.json',{'version':1,'checked_at':now.isoformat(),'checks':checks,
                       'status':'healthy' if all(checks.values()) else 'degraded','external_configured':bool(config.get('heartbeat_url'))})
        print('monitor_checked');return 0
    except Exception:
        print('monitor_failed; inspect private configuration and safe status reports')
        return 1


if __name__=='__main__':raise SystemExit(main())
