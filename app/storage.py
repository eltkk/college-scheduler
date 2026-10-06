from sqlalchemy import delete, select
from .config import settings
from .db import Workspace, Audit
from .domain import State
from .validation import RuleError, validate


class StaleVersion(RuleError):
    pass


def read_state(db):
    row = db.get(Workspace, 1)
    if row is None:
        raise RuleError("Приложение не инициализировано. Выполните команду настройки")
    return row.version, State.model_validate(row.payload)


def mutate(db, expected_version, user_id, action, operation):
    # Global lease prevents cross-course TOCTOU conflicts for all four editors.
    row = db.scalar(
        select(Workspace)
        .where(Workspace.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise RuleError("Приложение не инициализировано")
    if row.version != expected_version:
        raise StaleVersion(
            "Данные уже изменил другой пользователь. Обновите данные и повторите правку"
        )
    state = State.model_validate(row.payload)
    result = operation(state)
    validate(state)
    row.version += 1
    row.payload = state.model_dump(mode="json")
    db.add(
        Audit(version=row.version, user_id=user_id, action=action, snapshot=row.payload)
    )
    db.execute(
        delete(Audit).where(Audit.version < row.version - settings.history_versions + 1)
    )
    db.commit()
    return row.version, result
