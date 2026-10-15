"""Run only a unique disposable restore stack, then remove that exact stack."""
import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def read_env(path):
    result={}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,sep,value=line.partition('=')
        if not sep or key in result:raise ValueError('configuration_invalid')
        result[key]=value
    return result


def scope_url(value):
    parsed=urlsplit(value)
    if parsed.scheme!='postgresql+psycopg' or not parsed.hostname or not parsed.path or parsed.query or parsed.fragment:
        raise ValueError('source_scope_invalid')
    host='['+parsed.hostname+']' if ':' in parsed.hostname else parsed.hostname
    # No live DB username/password ever enters the isolated verifier.
    return 'postgresql+psycopg://scope@'+host+':'+str(parsed.port or 5432)+parsed.path


def main():
    import fcntl
    def stop(signum,frame):raise TimeoutError('restore_job_interrupted')
    signal.signal(signal.SIGTERM,stop)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('/etc/personal-crm/monitoring/restore-deploy.env'))
    args=parser.parse_args()
    report=None
    try:
        config=read_env(args.config)
        reports=Path(config['OPS_REPORT_DIRECTORY'])
        if reports.is_symlink() or not reports.is_dir():raise ValueError('report_directory_invalid')
        report=reports/'restore-last-run.json'
        with (reports/'restore.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            project='crm-restore-check-'+secrets.token_hex(6)
            if not re.fullmatch(r'crm-restore-check-[a-f0-9]{12}',project):raise ValueError()
            compose=Path(__file__).with_name('compose.restore-drill.yaml').resolve()
            with tempfile.TemporaryDirectory(prefix='crm-restore-check-',dir='/run') as private:
                private=Path(private);os.chmod(private,0o700)
                password=secrets.token_urlsafe(32)
                source=scope_url(read_env(Path(config['CRM_CONFIG_DIRECTORY'])/'database.env')['CRM_DATABASE_URL'])
                (private/'drill.env').write_text('CRM_DATABASE_URL='+source+'\nOPS_RESTORE_DATABASE_URL=postgresql+psycopg://drill:'+password+'@restore-db:5432/personal_crm_restore_drill\n')
                deployment={**config,'OPS_PRIVATE_RUN':str(private),'OPS_DRILL_PASSWORD':password}
                env_file=private/'deploy.env'
                env_file.write_text(''.join(key+'='+value+'\n' for key,value in deployment.items()))
                for item in private.iterdir():item.chmod(0o600)
                base=['/usr/bin/docker','compose','--env-file',str(env_file),'-p',project,'-f',str(compose)]
                def call(args,timeout):
                    return subprocess.run(base+args,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout,check=True)
                try:
                    call(['config','--quiet'],20)
                    call(['up','-d','--wait','restore-db'],100)
                    call(['run','--rm','-T','--interactive=false','--no-deps','verifier'],600)
                finally:
                    call(['down','--volumes','--remove-orphans','--timeout','10'],45)
        result=json.loads(report.read_text())
        if result['status']!='verified':raise ValueError('restore_not_verified')
        print('restore_drill_verified; disposable_stack_removed');return 0
    except Exception:
        if report is not None:
            # Record a wrapper/setup/timeout/cleanup failure too; never hide it behind old success.
            value={'version':1,'status':'failed','completed_at':datetime.now(UTC).isoformat(),'code':'restore_job_failed'}
            try:
                temp=report.with_name('.'+secrets.token_hex(6)+'.tmp')
                with temp.open('x') as stream:
                    temp.chmod(0o600);stream.write(json.dumps(value));stream.flush();os.fsync(stream.fileno())
                temp.replace(report)
            except OSError:pass
        print('restore_drill_failed; inspect safe last-run report');return 1


if __name__=='__main__':raise SystemExit(main())
