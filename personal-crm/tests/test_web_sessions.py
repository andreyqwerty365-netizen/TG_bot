from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from personal_crm.api import create_app
from personal_crm.config import Settings
from personal_crm.auth_config import WebAuthConfig
from personal_crm.models import Profile

OWNER = 'synthetic-owner'
PASSWORD = 'synthetic-web-session-password'
HASH = PasswordHasher().hash(PASSWORD)
ORIGIN = 'https://crm.example.invalid'


def settings(factory, **auth_changes):
    base = Settings(factory.kw['bind'].url.render_as_string(hide_password=False), OWNER,
                    'synthetic-bearer', timezone='Europe/Berlin')
    auth = dict(password_hash=HASH, origin=ORIGIN, allow_insecure_localhost=False)
    auth.update(auth_changes)
    return replace(base,web_auth=WebAuthConfig(**auth))


def client(factory, service, clock, **changes):
    app = create_app(settings(factory, **changes), service.interpreter)
    app.state.service.clock = clock
    return TestClient(app, base_url=changes.get('origin', ORIGIN))


def login(web, password=PASSWORD, origin=ORIGIN):
    return web.post('/auth/login', json={'password':password}, headers={'Origin':origin})


def test_login_survives_new_client_and_logout_revokes_cookie(factory, service, clock):
    web = client(factory, service, clock)
    assert web.get('/auth/session').status_code == 401
    response = login(web)
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert 'Max-Age=2592000' in cookie and 'Domain=' not in cookie
    assert PASSWORD not in response.text and HASH not in response.text
    csrf = response.json()['csrf_token']
    copied = web.cookies.get('__Host-crm_session')
    new = client(factory, service, clock)
    new.cookies.set('__Host-crm_session', copied, domain='crm.example.invalid', path='/')
    assert new.get('/workspace/settings').status_code == 200
    assert new.get('/auth/session').json()['csrf_token'] == csrf
    assert new.post('/auth/logout', headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code == 200
    assert web.get('/workspace/settings').status_code == 401


def test_cookie_writes_require_origin_and_session_bound_csrf(factory, service, clock):
    web = client(factory, service, clock)
    csrf = login(web).json()['csrf_token']
    body = {'request_id':'csrf-test','title':'Synthetic session task'}
    for headers in [{}, {'Origin':ORIGIN}, {'Origin':'https://evil.example.invalid','X-CSRF-Token':csrf},
                    {'Origin':ORIGIN,'X-CSRF-Token':'wrong'}]:
        assert web.post('/workspace/tasks',json=body,headers=headers).status_code == 403
    response = web.post('/workspace/tasks',json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['title'] == body['title']


def test_expiry_password_rotation_and_hold_reject_existing_session(factory, service, clock):
    web = client(factory, service, clock)
    assert login(web).status_code == 200
    rotated = client(factory, service, clock, password_hash=PasswordHasher().hash('synthetic-new-password'))
    rotated.cookies.update(web.cookies)
    assert rotated.get('/auth/session').status_code == 401
    with factory.begin() as s:
        s.get(Profile, OWNER).recovery_hold = True
    assert web.get('/workspace/settings').status_code == 503
    assert login(web).status_code == 503
    with factory.begin() as s:
        s.get(Profile, OWNER).recovery_hold = False
    clock.now += timedelta(days=30)
    assert web.get('/auth/session').status_code == 401


def test_login_csrf_and_persistent_limit_survive_new_process_app(factory, service, clock):
    web = client(factory, service, clock)
    assert login(web, origin='https://evil.example.invalid').status_code == 403
    assert web.post('/auth/login',json={'password':PASSWORD}).status_code == 403
    for _ in range(5):
        assert login(web,password='wrong synthetic password').status_code == 401
    recreated = client(factory, service, clock)
    blocked = login(recreated)
    assert blocked.status_code == 429 and blocked.headers.get('retry-after')
    clock.now += timedelta(minutes=15)
    assert login(recreated).status_code == 200


def test_concurrent_wrong_passwords_cannot_bypass_limit(factory, service, clock):
    def attempt(_):
        return login(client(factory,service,clock),password='wrong synthetic password').status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(attempt,range(6)))
    assert sorted(statuses) == [401,401,401,401,401,429]


def test_bearer_compatibility_and_insecure_cookie_only_for_loopback(factory, service, clock):
    web = client(factory,service,clock)
    assert web.get('/workspace/settings',headers={'Authorization':'Bearer synthetic-bearer'}).status_code == 200
    assert web.get('/workspace/settings',headers={'Authorization':'Bearer wrong'}).status_code == 401
    local = client(factory,service,clock,origin='http://127.0.0.1:8001',allow_insecure_localhost=True)
    response = login(local,origin='http://127.0.0.1:8001')
    assert response.status_code == 200 and 'Secure;' not in response.headers['set-cookie']
    assert local.get('/workspace/settings').status_code == 200
    unsafe = client(factory,service,clock,origin='http://crm.example.invalid',allow_insecure_localhost=True)
    assert login(unsafe,origin='http://crm.example.invalid').status_code == 503


def test_invalid_password_input_is_never_echoed(factory, service, clock):
    web = client(factory,service,clock)
    private_input = 'synthetic-secret-' * 100
    result = login(web,password=private_input)
    assert result.status_code == 422 and private_input not in result.text
