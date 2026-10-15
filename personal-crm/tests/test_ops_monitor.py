import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def module():
    spec=importlib.util.spec_from_file_location('ops_monitor',Path(__file__).parents[1]/'deploy'/'ops_monitor.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def test_two_failures_alert_once_and_recovery_requires_a_delivered_alert():
    m=module();state={};sent=[]
    notify=lambda message:sent.append(message)
    state=m.transition(state,{'https':False},notify)
    assert sent==[]
    state=m.transition(state,{'https':False},notify)
    assert len(sent)==1 and 'HTTPS' in sent[0]
    state=m.transition(state,{'https':False},notify)
    assert len(sent)==1
    state=m.transition(state,{'https':True},notify)
    assert len(sent)==1
    state=m.transition(state,{'https':True},notify)
    assert len(sent)==2 and 'Восстановлено' in sent[1]
    m.transition(state,{'https':True},notify)
    assert len(sent)==2


def test_failed_notification_is_retried_and_not_marked_sent():
    m=module();state={'https':{'bad':1,'good':0,'alerted':False}}
    def fail(message):raise OSError('secret token diagnostic')
    with pytest.raises(OSError):m.transition(state,{'https':False},fail)
    assert state['https']['alerted'] is False
    sent=[];state=m.transition(state,{'https':False},lambda msg:sent.append(msg))
    assert len(sent)==1 and state['https']['alerted']


def test_freshness_rejects_missing_future_and_stale_values():
    m=module();now=datetime(2026,10,15,12,tzinfo=UTC)
    assert m.is_recent(now.isoformat(),now,180)
    for value in (None,'invalid',now.replace(tzinfo=None).isoformat(),(now-timedelta(seconds=181)).isoformat(),(now+timedelta(minutes=3)).isoformat()):
        assert not m.is_recent(value,now,180)


def test_notification_text_never_uses_unknown_probe_or_exception_content():
    m=module();sent=[]
    with pytest.raises(ValueError):m.transition({}, {'private DSN':False},sent.append)
    assert sent==[]


def test_no_recovery_message_after_a_transient_failure():
    m=module();sent=[]
    state=m.transition({}, {'https':False},sent.append)
    state=m.transition(state, {'https':True},sent.append)
    state=m.transition(state, {'https':True},sent.append)
    assert sent==[]


def test_external_heartbeat_urls_are_constrained_and_never_redirected():
    m=module()
    for value in ('http://hc-ping.com/synthetic','https://evil.invalid/secret','https://user:secret@hc-ping.com/a','https://hc-ping.com/a?secret=b'):
        with pytest.raises(ValueError):m.heartbeat_url(value)
    assert m.heartbeat_url('https://hc-ping.com/00000000-0000-4000-8000-000000000000')=='https://hc-ping.com/00000000-0000-4000-8000-000000000000'


def test_multiple_failures_use_one_atomic_notification_batch():
    m=module();sent=[]
    state=m.transition({}, {'https':False,'source':False},sent.append)
    state=m.transition(state, {'https':False,'source':False},sent.append)
    assert len(sent)==1
    assert state['https']['alerted'] and state['source']['alerted']


def test_scope_only_url_removes_production_credentials():
    spec=importlib.util.spec_from_file_location('restore_job',Path(__file__).parents[1]/'deploy'/'restore_drill_job.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.scope_url('postgresql+psycopg://private:secret@db:5432/personal_crm')=='postgresql+psycopg://scope@db:5432/personal_crm'


def test_monitor_rejects_failed_backup_report_even_with_recent_time(tmp_path,monkeypatch):
    m=module();now=datetime(2026,10,15,12,tzinfo=UTC)
    report=tmp_path/'legacy.json';report.write_text(json.dumps({'status':'failed','created_at':now.isoformat()}))
    monkeypatch.setattr(m,'request',lambda *args,**kwargs:b'{"status":"ready"}')
    monkeypatch.setattr(m,'command',lambda *args:'true healthy')
    checks=m.collect({'crm_origin':'https://example.invalid','legacy_backup_report':str(report),'restore_report':str(tmp_path/'missing.json')},now)
    assert checks['legacy_backup'] is False


def test_cronitor_heartbeat_uses_its_fixed_origin_and_failure_protocol(monkeypatch):
    m=module();sent=[]
    value='https://cronitor.link/p/'+('a'*32)+'/crm-ops-heartbeat'
    assert m.heartbeat_url(value)==value
    monkeypatch.setattr(m,'request',lambda host,path:sent.append((host,path)))
    m.ping(value);m.ping(value,failed=True)
    assert sent==[('cronitor.link','/p/'+('a'*32)+'/crm-ops-heartbeat'),('cronitor.link','/p/'+('a'*32)+'/crm-ops-heartbeat?state=fail')]
