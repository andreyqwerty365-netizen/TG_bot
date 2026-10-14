"""Opaque owner-only sessions. Secrets never enter JSON, URLs or access logs."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import delete, or_, select

from .models import LoginThrottle, Profile, WebSession
from .schema import Strict

SESSION_SECONDS = 30 * 24 * 3600


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Login(Strict):
    password: str = Field(min_length=1,max_length=1024,repr=False)


def install_auth(app, service, settings):
    factory, config = service.factory, settings.web_auth
    secure = not config.allow_insecure_localhost
    cookie_name = '__Host-crm_session' if secure else 'crm_local_session'
    credential_version = digest(config.password_hash)

    def configured():
        if not settings.owner_id or not config.valid(settings.environment):
            raise HTTPException(503,'web_auth_not_configured')

    def origin_check(request):
        configured()
        actual = f'{request.url.scheme}://{request.url.netloc}'
        if request.headers.get('origin') != config.origin or actual != config.origin:
            raise HTTPException(403,'csrf_forbidden')

    def locked_profile(s):
        profile = s.scalar(select(Profile).where(Profile.id == settings.owner_id).with_for_update())
        if not profile:
            raise HTTPException(503,'owner_not_configured')
        if profile.recovery_hold:
            raise HTTPException(503,'recovery_hold')
        return profile

    def session(s, request, write=False):
        configured()
        raw = request.cookies.get(cookie_name,'')
        if not raw or len(raw)>128:
            raise HTTPException(401,'unauthorized')
        locked_profile(s)
        current = s.get(WebSession,digest(raw))
        if (not current or current.owner_id != settings.owner_id or current.revoked
            or current.expires_at <= service.clock() or current.credential_version != credential_version):
            raise HTTPException(401,'unauthorized')
        if write:
            origin_check(request)
            csrf = request.headers.get('x-csrf-token','')
            if not hmac.compare_digest(csrf.encode(),current.csrf_token.encode()):
                raise HTTPException(403,'csrf_forbidden')
        return current

    def actor(request: Request):
        authorization = request.headers.get('authorization')
        if authorization is not None:
            if not settings.owner_id or not settings.owner_token:
                raise HTTPException(503,'owner_not_configured')
            expected = 'Bearer '+settings.owner_token
            if not hmac.compare_digest(authorization.encode(),expected.encode()):
                raise HTTPException(401,'unauthorized')
            service.register(settings.owner_id,settings.timezone,initialize_only=True)
            with factory.begin() as s:
                locked_profile(s)
        else:
            if not request.cookies.get(cookie_name):
                if not settings.owner_id or not (settings.owner_token or config.password_hash):
                    raise HTTPException(503,'owner_not_configured')
                raise HTTPException(401,'unauthorized')
            with factory.begin() as s:
                session(s,request,write=request.method not in ('GET','HEAD','OPTIONS'))
        return settings.owner_id

    @app.post('/auth/login')
    def login(body: Login, request: Request):
        origin_check(request)
        service.register(settings.owner_id,settings.timezone,initialize_only=True)
        now = service.clock()
        failure, wait = False, None
        with factory.begin() as s:
            locked_profile(s)  # Serializes expensive verification and all rate counters.
            s.execute(delete(LoginThrottle).where(LoginThrottle.owner_id==settings.owner_id,
                LoginThrottle.window_at <= now-timedelta(minutes=15)))
            buckets = []
            # Per-IP limit avoids letting one remote client lock out the owner globally.
            # Aggregate ceiling also bounds distributed guesses; IP comes from trusted ASGI transport, never raw headers.
            for value, limit in [('owner',50),('ip:'+((request.client.host if request.client else '') or 'unknown'),5)]:
                key = digest(settings.owner_id+'\0'+value)
                bucket = s.get(LoginThrottle,key)
                if not bucket:
                    bucket = LoginThrottle(bucket_key=key,owner_id=settings.owner_id,window_at=now,failures=0)
                    s.add(bucket)
                if now >= bucket.window_at+timedelta(minutes=15):
                    bucket.window_at,bucket.failures = now,0
                if bucket.failures >= limit:
                    wait = max(1,int((bucket.window_at+timedelta(minutes=15)-now).total_seconds()))
                buckets.append(bucket)
                if wait is not None:
                    break
            if wait is None:
                try:
                    PasswordHasher().verify(config.password_hash,body.password)
                except VerifyMismatchError:
                    failure = True
                    for bucket in buckets:
                        bucket.failures += 1
                except (VerificationError,InvalidHashError):
                    raise HTTPException(503,'web_auth_not_configured') from None
                if not failure:
                    for bucket in buckets:
                        bucket.failures = 0
                    s.execute(delete(WebSession).where(WebSession.owner_id == settings.owner_id,
                        or_(WebSession.expires_at <= now,WebSession.revoked.is_(True),WebSession.credential_version != credential_version)))
                    existing = list(s.scalars(select(WebSession).where(WebSession.owner_id == settings.owner_id).order_by(WebSession.created_at)))
                    for old in existing[:-19]:
                        s.delete(old)
                    raw = secrets.token_urlsafe(32)
                    csrf = secrets.token_urlsafe(32)
                    s.add(WebSession(token_hash=digest(raw),owner_id=settings.owner_id,credential_version=credential_version,
                                     csrf_token=csrf,created_at=now,expires_at=now+timedelta(seconds=SESSION_SECONDS)))
        # Errors outside the transaction preserve persistent throttling across restarts.
        if wait is not None:
            raise HTTPException(429,'login_rate_limited',headers={'Retry-After':str(wait)})
        if failure:
            raise HTTPException(401,'unauthorized')
        response = JSONResponse({'authenticated':True,'csrf_token':csrf},headers={'Cache-Control':'no-store'})
        response.set_cookie(cookie_name,raw,max_age=SESSION_SECONDS,secure=secure,httponly=True,samesite='strict',path='/')
        return response

    @app.get('/auth/session')
    def current_session(request: Request):
        with factory.begin() as s:
            current = session(s,request)
            return JSONResponse({'authenticated':True,'csrf_token':current.csrf_token},headers={'Cache-Control':'no-store'})

    @app.post('/auth/logout')
    def logout(request: Request):
        with factory.begin() as s:
            current = session(s,request,write=True)
            current.revoked = True
        response = JSONResponse({'authenticated':False},headers={'Cache-Control':'no-store'})
        response.delete_cookie(cookie_name,path='/',secure=secure,httponly=True,samesite='strict')
        return response

    return actor
