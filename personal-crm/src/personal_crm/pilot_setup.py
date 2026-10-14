"""Owner-only initial setup; no deployment or external integration side effects."""
import argparse
import getpass
import json
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import Settings
from .db import sessions
from .models import Profile


def password_hash():
    password=getpass.getpass('Новый пароль (от 12 символов): ')
    confirmation=getpass.getpass('Повторите пароль: ')
    if len(password)<12 or len(password)>1024 or password!=confirmation:
        raise ValueError('password_confirmation_invalid')
    return PasswordHasher().hash(password)


def initialize_owner(config):
    if not config.owner_id or len(config.owner_id)>64 or not config.timezone:
        raise ValueError('owner_and_timezone_required')
    ZoneInfo(config.timezone)
    factory=sessions(config.database_url)
    try:
        with factory.begin() as s:
            created=s.execute(insert(Profile).values(id=config.owner_id,timezone=config.timezone,digest_hour=9,
                initiative_limit=1,catchup_grace_seconds=3600).on_conflict_do_nothing().returning(Profile.id)).scalar()
            current=s.scalar(select(Profile).where(Profile.id==config.owner_id))
            if current.timezone!=config.timezone or current.recovery_hold:
                raise ValueError('existing_owner_configuration_conflict')
        return {'status':'owner_initialized' if created else 'owner_already_initialized'}
    finally:
        factory.kw['bind'].dispose()


def main():
    parser=argparse.ArgumentParser(description='Owner setup; password is entered privately, never as an argument')
    parser.add_argument('command',choices=['password-hash','initialize-owner'])
    args=parser.parse_args()
    if args.command=='password-hash':
        try:print(password_hash())
        except ValueError:raise SystemExit('password_confirmation_invalid') from None
    else:
        try:print(json.dumps(initialize_owner(Settings.from_env())))
        except Exception:raise SystemExit('owner_setup_failed') from None


if __name__=='__main__':main()
