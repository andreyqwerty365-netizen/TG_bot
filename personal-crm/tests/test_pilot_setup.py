import pytest
from sqlalchemy import select
from personal_crm.config import Settings
from personal_crm.models import Profile


def test_initial_owner_gets_moscow_morning_without_overwriting_later_choices(factory):
    from personal_crm.pilot_setup import initialize_owner
    config=Settings(factory.kw['bind'].url.render_as_string(hide_password=False),'synthetic-owner',timezone='Europe/Moscow')
    assert initialize_owner(config)['status']=='owner_initialized'
    with factory.begin() as s:s.get(Profile,'synthetic-owner').digest_hour=11
    assert initialize_owner(config)['status']=='owner_already_initialized'
    with factory() as s:assert s.get(Profile,'synthetic-owner').digest_hour==11


def test_password_setup_does_not_accept_mismatch_or_short_password(monkeypatch,capsys):
    from personal_crm.pilot_setup import password_hash
    for answers in [['tiny','tiny'],['synthetic-secret-long','different-secret']]:
        values=iter(answers);monkeypatch.setattr('getpass.getpass',lambda _:next(values))
        with pytest.raises(ValueError):password_hash()
        assert capsys.readouterr().out==''
    values=iter(['synthetic-secret-long']*2);monkeypatch.setattr('getpass.getpass',lambda _:next(values))
    encoded=password_hash()
    from argon2 import PasswordHasher
    assert PasswordHasher().verify(encoded,'synthetic-secret-long')
