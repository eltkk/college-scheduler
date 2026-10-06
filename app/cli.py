import argparse
import getpass
import json
import os
from sqlalchemy import select
from .auth import hasher
from .db import Audit, LoginSession, SessionLocal, User, Workspace
from .domain import State, uid


def initialize(demo=False):
    with SessionLocal() as db:
        if db.get(Workspace, 1) is None:
            if demo:
                from .demo import demo_state

                state = demo_state()
            else:
                state = State()
            raw = state.model_dump(mode="json")
            db.add(Workspace(id=1, version=0, payload=raw))
            db.add(
                Audit(version=0, user_id="system", action="Инициализация", snapshot=raw)
            )
        bootstrap = os.getenv("BOOTSTRAP_USERS")
        if bootstrap and not db.scalar(select(User).limit(1)):
            users = json.loads(bootstrap)
            if not isinstance(users, list) or len(users) != 4:
                raise ValueError("BOOTSTRAP_USERS должен содержать четыре аккаунта")
            if len({u["login"] for u in users}) != 4:
                raise ValueError("Логины должны быть уникальными")
            for user in users:
                create_user(
                    db, user["login"], user.get("name", user["login"]), user["password"]
                )
        db.commit()


def create_user(db, login, name, password):
    if password.startswith("REPLACE_"):
        raise ValueError(
            "Замените пример пароля в BOOTSTRAP_USERS на уникальный пароль"
        )
    if len(password) < 12 or len(password) > 200:
        raise ValueError("Пароль должен содержать от 12 до 200 символов")
    if not login.strip() or len(login) > 100 or not name or len(name) > 200:
        raise ValueError("Неверный логин или имя")
    if db.scalar(select(User).where(User.login == login)):
        raise ValueError("Логин уже существует")
    db.add(
        User(
            id=uid(),
            login=login.strip(),
            name=name,
            password_hash=hasher.hash(password),
        )
    )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--demo", action="store_true")
    user = sub.add_parser("user")
    user.add_argument("--login", required=True)
    user.add_argument("--name", required=True)
    password = sub.add_parser("password")
    password.add_argument("--login", required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.demo)
    elif args.command == "user":
        with SessionLocal() as db:
            create_user(db, args.login, args.name, getpass.getpass("Новый пароль: "))
            db.commit()
    else:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login == args.login))
            if user is None:
                raise ValueError("Пользователь не найден")
            value = getpass.getpass("Новый пароль: ")
            if not 12 <= len(value) <= 200:
                raise ValueError("Пароль должен содержать от 12 до 200 символов")
            user.password_hash = hasher.hash(value)
            for session in db.scalars(
                select(LoginSession).where(LoginSession.user_id == user.id)
            ):
                db.delete(session)
            db.commit()


if __name__ == "__main__":
    main()
