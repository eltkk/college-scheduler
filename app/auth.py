import hashlib
import secrets
from datetime import timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from .config import settings
from .db import LoginSession, LoginAttempt, SessionLocal, User, now

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def db_session():
    with SessionLocal() as db:
        yield db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def identity(request: Request, db=Depends(db_session)):
    token = request.cookies.get("scheduler_session", "")
    entry = db.get(LoginSession, digest(token)) if token else None
    if entry is None or aware(entry.expires) <= now():
        raise HTTPException(401, "Войдите в приложение")
    user = db.get(User, entry.user_id)
    if user is None:
        raise HTTPException(401, "Пользователь не найден")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(
        request.headers.get("X-CSRF-Token", ""), entry.csrf
    ):
        raise HTTPException(403, "Защита запроса: обновите страницу")
    return user, entry


def login(db, username, password, client_ip):
    key = digest(username.strip().casefold() + "|" + client_ip)
    attempt = db.get(LoginAttempt, key)
    if (
        attempt
        and now() - aware(attempt.since) < timedelta(minutes=15)
        and attempt.failures >= 10
    ):
        raise HTTPException(429, "Слишком много попыток. Повторите вход через 15 минут")
    entered_login = username.strip()
    user = db.scalar(select(User).where(User.login == entered_login))
    if user is None:
        matches = db.scalars(
            select(User).where(func.lower(User.login) == entered_login.lower()).limit(2)
        ).all()
        if len(matches) == 1:
            user = matches[0]
    valid = False
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
    except VerificationError:
        pass
    if user is None or not valid:
        if attempt is None:
            attempt = LoginAttempt(key=key, failures=0, since=now())
            db.add(attempt)
        if now() - aware(attempt.since) >= timedelta(minutes=15):
            attempt.failures = 0
            attempt.since = now()
        attempt.failures += 1
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    if attempt:
        db.delete(attempt)
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(24)
    entry = LoginSession(
        token_hash=digest(token),
        user_id=user.id,
        csrf=csrf,
        expires=now() + timedelta(hours=settings.session_hours),
    )
    db.add(entry)
    db.commit()
    return user, entry, token
