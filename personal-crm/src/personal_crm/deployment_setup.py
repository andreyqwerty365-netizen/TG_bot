"""Offline operator configuration. No environment discovery, networking or deployment."""
import argparse
import base64
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from .pilot_setup import password_hash

REPOSITORY=Path(__file__).resolve().parents[3]
DEFAULTS={
    'database.env':{'CRM_DATABASE_URL':''},
    'identity.env':{'CRM_OWNER_ID':'','CRM_TIMEZONE':'Europe/Moscow'},
    'deploy.env':{'CRM_HOST':'','ACME_EMAIL':'','CRM_IMAGE':'','CRM_BACKUP_IMAGE':'','CRM_CONFIG_DIRECTORY':''},
    'web.env':{'CRM_WEB_PASSWORD_HASH':'','CRM_WEB_ORIGIN':'','CRM_OWNER_TOKEN':'',
               'CRM_TELEGRAM_SEND_ENABLED':'false','CRM_BACKUP_ENABLED':'false','CRM_S3_ENABLED':'false'},
    'ingress.env':{'CRM_TELEGRAM_WEBHOOK_ENABLED':'false','CRM_TELEGRAM_WEBHOOK_SECRET':'',
        'CRM_TELEGRAM_BOT_ID':'','CRM_TELEGRAM_ALLOWED_USER_IDS':'','CRM_TELEGRAM_ALLOWED_CHAT_IDS':'',
        'CRM_TELEGRAM_ALLOW_GROUPS':'false'},
    'delivery.env':{'CRM_TELEGRAM_SEND_ENABLED':'false','CRM_TELEGRAM_TEST_TOKEN':'','CRM_TELEGRAM_BOT_ID':'',
        'CRM_TELEGRAM_ALLOWED_USER_IDS':'','CRM_TELEGRAM_ALLOWED_CHAT_IDS':'',
        'CRM_TELEGRAM_OUTBOUND_CHAT_ID':'','CRM_TELEGRAM_ALLOW_GROUPS':'false'},
    'backup.env':{'CRM_BACKUP_ENABLED':'false','CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED':'false','CRM_BACKUP_KEY':'',
        'CRM_S3_ENABLED':'false','CRM_S3_ENDPOINT':'','CRM_S3_BUCKET':'','CRM_S3_ACCESS_KEY':'',
        'CRM_S3_SECRET_KEY':'','CRM_S3_REGION':'ru-1','CRM_S3_PREFIX':'personal-crm'},
}


def require_linux():
    if not sys.platform.startswith('linux'):raise ValueError('linux_operator_command_required')


def hostname(value):
    if len(value)>253 or not re.fullmatch(r'[a-z0-9.-]+',value) or '.' not in value:
        raise ValueError('dns_hostname_required')
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.')):
        raise ValueError('dns_hostname_required')
    try:ipaddress.ip_address(value)
    except ValueError:return value
    raise ValueError('dns_hostname_required')


def public_settings(host,email,image,backup_image):
    hostname(host)
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email):
        raise ValueError('certificate_email_invalid')
    if not all(re.fullmatch(r'sha256:[a-f0-9]{64}',x) for x in (image,backup_image)):
        raise ValueError('immutable_local_image_ids_required')


def config_path(directory):
    path=Path(directory)
    if not path.is_absolute() or not path.name or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('absolute_unlinked_directory_required')
    if any(c in str(path) for c in '\r\n\x00$#\'" '):raise ValueError('configuration_path_invalid')
    return path


def render_configuration(*,directory,host,email,image,backup_image,password=None,encoded_password=None):
    """Pure rendering also used by the isolated container rehearsal."""
    directory=config_path(directory)
    public_settings(host,email,image,backup_image)
    if encoded_password is None:
        if password is None or not 12<=len(password)<=1024:raise ValueError('password_length_invalid')
        encoded_password=PasswordHasher().hash(password)
    data={name:dict(values) for name,values in DEFAULTS.items()}
    db_password=secrets.token_urlsafe(36)
    data['database.env']['CRM_DATABASE_URL']=URL.create('postgresql+psycopg',username='crm',password=db_password,
        host='db',port=5432,database='personal_crm').render_as_string(hide_password=False)
    data['identity.env']['CRM_OWNER_ID']='owner-'+secrets.token_hex(16)
    data['deploy.env'].update(CRM_HOST=host,ACME_EMAIL=email,CRM_IMAGE=image,CRM_BACKUP_IMAGE=backup_image,
                              CRM_CONFIG_DIRECTORY=str(directory))
    data['web.env'].update(CRM_WEB_PASSWORD_HASH=encoded_password,CRM_WEB_ORIGIN='https://'+host)
    data['backup.env']['CRM_BACKUP_KEY']=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    files={name:''.join(key+'='+value+'\n' for key,value in values.items()) for name,values in data.items()}
    files['db-password']=db_password+'\n'
    return files


def generate(**options):
    directory=config_path(options['directory'])
    if directory.resolve().is_relative_to(REPOSITORY.resolve()):
        raise ValueError('configuration_outside_checkout_required')
    if directory.exists():raise ValueError('configuration_directory_exists')
    files=render_configuration(**options)
    # mkdir is exclusive. An incomplete directory is deliberately retained on failure:
    # operator recovery must not silently regenerate database/encryption credentials.
    directory.mkdir(mode=0o700)
    for name,content in files.items():
        descriptor=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:stream.write(content)
    return {'status':'configuration_created','files':len(files),'integrations_enabled':False,
            'next':'keep_backup_key_off_server_then_check_configuration'}


def private_metadata(path,*,directory=False):
    info=path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('regular_private_file_required')
    if os.name!='nt' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=(0o700 if directory else 0o600)):
        raise ValueError('private_permissions_required')


def read_private(path):
    private_metadata(path)
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(descriptor,'r',encoding='utf-8') as stream:
        text=stream.read(32769)
    if len(text)>32768 or '\x00' in text:raise ValueError('configuration_file_invalid')
    return text


def read_values(path,expected):
    result={}
    for line in read_private(path).splitlines():
        if not line or line.startswith('#'):continue
        if '=' not in line:raise ValueError('configuration_format_invalid')
        key,value=line.split('=',1)
        if key not in expected or key in result:raise ValueError('configuration_keys_invalid')
        result[key]=value
    if result.keys()!=expected.keys():raise ValueError('configuration_keys_invalid')
    return result


def flag(values,key):
    value=values[key]
    if value not in ('true','false'):raise ValueError('boolean_flag_invalid')
    return value=='true'


def check_integrations(data):
    web,ingress,delivery,backup=(data[n+'.env'] for n in ('web','ingress','delivery','backup'))
    send=flag(delivery,'CRM_TELEGRAM_SEND_ENABLED');receive=flag(ingress,'CRM_TELEGRAM_WEBHOOK_ENABLED')
    if flag(web,'CRM_TELEGRAM_SEND_ENABLED')!=send:raise ValueError('integration_flags_mismatch')
    for values in (ingress,delivery):flag(values,'CRM_TELEGRAM_ALLOW_GROUPS')
    for enabled,values in ((send,delivery),(receive,ingress)):
        if not enabled:continue
        try:
            bot=int(values['CRM_TELEGRAM_BOT_ID'])
            users={int(x) for x in values['CRM_TELEGRAM_ALLOWED_USER_IDS'].split(',')}
            chats={int(x) for x in values['CRM_TELEGRAM_ALLOWED_CHAT_IDS'].split(',')}
            if bot<=0 or len(users)!=1 or min(users)<=0 or len(chats)!=1 or 0 in chats:raise ValueError()
            if not flag(values,'CRM_TELEGRAM_ALLOW_GROUPS') and min(chats)<0:raise ValueError()
            if send and values is delivery:
                token=values['CRM_TELEGRAM_TEST_TOKEN']
                if not re.fullmatch(str(bot)+r':[A-Za-z0-9_-]{20,}',token):raise ValueError()
                if int(values['CRM_TELEGRAM_OUTBOUND_CHAT_ID']) not in chats:raise ValueError()
            if receive and values is ingress and not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',values['CRM_TELEGRAM_WEBHOOK_SECRET']):
                raise ValueError()
        except ValueError:raise ValueError('telegram_configuration_invalid') from None
    if send and receive:
        for key in ('CRM_TELEGRAM_BOT_ID','CRM_TELEGRAM_ALLOWED_USER_IDS','CRM_TELEGRAM_ALLOWED_CHAT_IDS','CRM_TELEGRAM_ALLOW_GROUPS'):
            if ingress[key]!=delivery[key]:raise ValueError('telegram_identity_mismatch')
    enabled=flag(backup,'CRM_BACKUP_ENABLED');remote=flag(backup,'CRM_S3_ENABLED')
    confirmed=flag(backup,'CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED')
    if flag(web,'CRM_BACKUP_ENABLED')!=enabled or flag(web,'CRM_S3_ENABLED')!=remote:
        raise ValueError('integration_flags_mismatch')
    if enabled!=remote or (enabled and not confirmed):raise ValueError('external_backup_required')
    try:
        if len(base64.b64decode(backup['CRM_BACKUP_KEY'],altchars=b'-_',validate=True))!=32:raise ValueError()
    except ValueError:raise ValueError('backup_key_invalid') from None
    if enabled:
        from .remote_backup import S3Config, validate
        from .recovery import RecoveryError
        try:validate(S3Config(True,*(backup[key] for key in ('CRM_S3_ENDPOINT','CRM_S3_BUCKET','CRM_S3_ACCESS_KEY',
            'CRM_S3_SECRET_KEY','CRM_S3_REGION','CRM_S3_PREFIX'))))
        except (RecoveryError,ValueError):raise ValueError('s3_configuration_invalid') from None
    return {'telegram':'configured_unverified' if send or receive else 'disabled',
            'backup':'configured_unverified' if enabled else 'disabled','mail':'disabled','ai':'disabled'}


def check(directory):
    """Read exactly the selected private directory; never import it into os.environ."""
    directory=config_path(directory);private_metadata(directory,directory=True)
    data={name:read_values(directory/name,expected) for name,expected in DEFAULTS.items()}
    deploy=data['deploy.env'];public_settings(deploy['CRM_HOST'],deploy['ACME_EMAIL'],deploy['CRM_IMAGE'],deploy['CRM_BACKUP_IMAGE'])
    if Path(deploy['CRM_CONFIG_DIRECTORY'])!=directory:raise ValueError('configuration_directory_mismatch')
    identity=data['identity.env']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',identity['CRM_OWNER_ID']):raise ValueError('owner_invalid')
    try:ZoneInfo(identity['CRM_TIMEZONE'])
    except (ValueError,KeyError):raise ValueError('timezone_invalid') from None
    try:url=make_url(data['database.env']['CRM_DATABASE_URL'])
    except (ArgumentError,ValueError):raise ValueError('database_configuration_invalid') from None
    if (url.drivername!='postgresql+psycopg' or url.username!='crm' or url.host!='db' or url.port!=5432
        or url.database!='personal_crm' or url.query or not url.password or len(url.password)<24):
        raise ValueError('database_configuration_invalid')
    if url.password!=read_private(directory/'db-password').removesuffix('\n'):
        raise ValueError('database_credentials_mismatch')
    web=data['web.env']
    if web['CRM_WEB_ORIGIN']!='https://'+deploy['CRM_HOST']:raise ValueError('web_origin_mismatch')
    try:
        params=extract_parameters(web['CRM_WEB_PASSWORD_HASH'])
        if params.type!=Type.ID or params.version!=19 or params.memory_cost<19456 or params.time_cost<2 or params.salt_len<16:
            raise ValueError()
    except (ValueError,TypeError):raise ValueError('password_hash_invalid') from None
    integrations=check_integrations(data)
    return {'status':'configuration_valid','integrations':integrations,
            'not_checked':['image_availability','docker_compose','dns','public_https','database_connection',
                           'workers','telegram_identity_and_delivery','remote_backup','remote_restore','vps_reboot']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    generate_parser=commands.add_parser('generate',help='NEW private directory only; password entered without echo')
    generate_parser.add_argument('--directory',type=Path,required=True)
    for name in ('host','email','image','backup-image'):generate_parser.add_argument('--'+name,required=True)
    check_parser=commands.add_parser('check',help='Offline file checks only; no readiness claim')
    check_parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        require_linux()
        if args.command=='generate':
            # Validate public inputs/target BEFORE asking for a password.
            public_settings(args.host,args.email,args.image,args.backup_image)
            directory=config_path(args.directory)
            if directory.exists():raise ValueError('configuration_directory_exists')
            if not sys.stdin.isatty():raise ValueError('private_terminal_required')
            result=generate(directory=directory,host=args.host,email=args.email,image=args.image,
                            backup_image=args.backup_image,encoded_password=password_hash())
        else:result=check(args.directory)
        print(json.dumps(result));return 0
    except (OSError,ValueError,KeyError):
        # Neither exception text nor paths/values belong in shared terminal logs.
        print('configuration_invalid; inspect private operator files and setup instructions',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
