from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
import hashlib
import json
import re
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .auth import db_session, identity, login
from .config import settings
from .db import Audit, GenerationJob, ImportDocument, User, Workspace, health, now
from .domain import (
    CATALOG_MODELS,
    Allocation,
    CollegeSettings,
    Lesson,
    Requirement,
    State,
    Subject,
    Teacher,
    Group,
    uid,
    college_profile,
)
from .export import export_schedule, load_template
from .imports import parse_kug, parse_load
from .word_load import parse_word_load
from .storage import StaleVersion, mutate, read_state
from .validation import RuleError, report, validate, leaf_groups

app = FastAPI(
    title="Расписание колледжа", version="0.1.0", docs_url=None, redoc_url=None
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[x.strip() for x in settings.allowed_hosts.split(",")],
)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api") else "no-cache"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response


@app.exception_handler(RuleError)
async def rules(request, exc):
    return JSONResponse(
        status_code=409 if isinstance(exc, StaleVersion) else 422,
        content={"detail": exc.messages},
    )


@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        status_code=422, content={"detail": [e["msg"] for e in exc.errors()]}
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": "Данные уже были сохранены. Обновите страницу"},
    )


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class Change(BaseModel):
    version: int = Field(ge=0)
    item: dict[str, Any]


class Lease(BaseModel):
    version: int = Field(ge=0)


def parse_week(value):
    try:
        week = date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise RuleError("Укажите дату понедельника в формате ГГГГ-ММ-ДД")
    if week.weekday() != 0:
        raise RuleError("Неделя должна начинаться с понедельника")
    return week


@app.get("/api/health")
def healthcheck():
    health()
    return {"status": "ok"}


@app.post("/api/auth/login")
def sign_in(
    body: Credentials, request: Request, response: Response, db=Depends(db_session)
):
    user, entry, token = login(
        db,
        body.login,
        body.password,
        request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        "scheduler_session",
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    return {"name": user.name, "login": user.login, "csrf": entry.csrf}


@app.get("/api/auth/me")
def me(auth=Depends(identity)):
    user, entry = auth
    return {"name": user.name, "login": user.login, "csrf": entry.csrf}


@app.post("/api/auth/logout")
def sign_out(response: Response, auth=Depends(identity), db=Depends(db_session)):
    db.delete(auth[1])
    db.commit()
    response.delete_cookie("scheduler_session", path="/")
    return {"ok": True}


@app.get("/api/state")
def state(auth=Depends(identity), db=Depends(db_session)):
    version, current = read_state(db)
    return {"version": version, "state": current.model_dump(mode="json")}


@app.put("/api/catalog/{kind}/{item_id}")
def catalog(
    kind: str,
    item_id: str,
    body: Change,
    auth=Depends(identity),
    db=Depends(db_session),
):
    if kind not in CATALOG_MODELS:
        raise HTTPException(404, "Справочник не найден")
    parsed = CATALOG_MODELS[kind].model_validate({**body.item, "id": item_id})
    version, _ = mutate(
        db,
        body.version,
        auth[0].id,
        "Изменение справочника",
        lambda s: getattr(s, kind).__setitem__(item_id, parsed),
    )
    return {"version": version, "item": parsed.model_dump(mode="json")}


@app.delete("/api/catalog/{kind}/{item_id}")
def delete_catalog(
    kind: str,
    item_id: str,
    version: int,
    auth=Depends(identity),
    db=Depends(db_session),
):
    if kind not in CATALOG_MODELS:
        raise HTTPException(404, "Справочник не найден")

    def change(s):
        if item_id not in getattr(s, kind):
            raise HTTPException(404, "Запись не найдена")
        del getattr(s, kind)[item_id]

    v, _ = mutate(db, version, auth[0].id, "Удаление из справочника", change)
    return {"version": v}


@app.put("/api/settings")
def edit_settings(body: Change, auth=Depends(identity), db=Depends(db_session)):
    parsed = CollegeSettings.model_validate(body.item)
    v, _ = mutate(
        db,
        body.version,
        auth[0].id,
        "Учебный календарь",
        lambda s: setattr(s, "settings", parsed),
    )
    return {"version": v}


@app.get("/api/settings/college-profile")
def settings_profile(auth=Depends(identity)):
    return college_profile().model_dump(mode="json")


@app.put("/api/requirements/{item_id}")
def requirement(
    item_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)
):
    parsed = Requirement.model_validate({**body.item, "id": item_id})
    v, _ = mutate(
        db,
        body.version,
        auth[0].id,
        "Учебная нагрузка",
        lambda s: s.requirements.__setitem__(item_id, parsed),
    )
    return {"version": v}


@app.delete("/api/requirements/{item_id}")
def delete_requirement(
    item_id: str, version: int, auth=Depends(identity), db=Depends(db_session)
):
    def change(s):
        if item_id not in s.requirements:
            raise HTTPException(404, "Нагрузка не найдена")
        del s.requirements[item_id]

    v, _ = mutate(db, version, auth[0].id, "Удаление нагрузки", change)
    return {"version": v}


@app.put("/api/lessons/{item_id}")
def lesson(item_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)):
    parsed = Lesson.model_validate({"locked": True, **body.item, "id": item_id})
    v, _ = mutate(
        db,
        body.version,
        auth[0].id,
        "Изменение занятия",
        lambda s: s.lessons.__setitem__(item_id, parsed),
    )
    return {"version": v}


@app.delete("/api/lessons/{item_id}")
def delete_lesson(
    item_id: str, version: int, auth=Depends(identity), db=Depends(db_session)
):
    def change(s):
        if item_id not in s.lessons:
            raise HTTPException(404, "Занятие не найдено")
        del s.lessons[item_id]

    v, _ = mutate(db, version, auth[0].id, "Удаление занятия", change)
    return {"version": v}


@app.post("/api/lessons/swap")
def swap(body: Change, auth=Depends(identity), db=Depends(db_session)):
    def change(s):
        a = s.lessons.get(body.item.get("first"))
        b = s.lessons.get(body.item.get("second"))
        if a is None or b is None or a.id == b.id:
            raise RuleError("Выберите два разных занятия")
        # Validate complete replacements, avoiding transient invalid start/end values.
        s.lessons[a.id] = Lesson.model_validate(
            {
                **a.model_dump(),
                "day": b.day,
                "start": b.start,
                "end": b.end,
                "locked": True,
            }
        )
        s.lessons[b.id] = Lesson.model_validate(
            {
                **b.model_dump(),
                "day": a.day,
                "start": a.start,
                "end": a.end,
                "locked": True,
            }
        )

    v, _ = mutate(db, body.version, auth[0].id, "Обмен занятий", change)
    return {"version": v}


@app.get("/api/check")
def check(week: date | None = None, auth=Depends(identity), db=Depends(db_session)):
    _, s = read_state(db)
    return report(s, week)


@app.get("/api/history")
def history(auth=Depends(identity), db=Depends(db_session)):
    rows = db.scalars(
        select(Audit).order_by(Audit.version.desc()).limit(settings.history_versions)
    ).all()
    names = {u.id: u.name for u in db.scalars(select(User))}
    return [
        {
            "version": r.version,
            "action": r.action,
            "at": r.at.isoformat(),
            "user_id": r.user_id,
            "user_name": names.get(r.user_id, "Система"),
        }
        for r in rows
    ]


@app.post("/api/history/{target}/restore")
def restore(target: int, body: Lease, auth=Depends(identity), db=Depends(db_session)):
    audit = db.scalar(select(Audit).where(Audit.version == target))
    if audit is None:
        raise HTTPException(404, "Версия не найдена")
    saved = State.model_validate(audit.snapshot)

    def change(s):
        for field in State.model_fields:
            setattr(s, field, getattr(saved, field))

    v, _ = mutate(
        db, body.version, auth[0].id, f"Восстановление версии {target}", change
    )
    return {"version": v}


@app.post("/api/imports")
def upload(
    file: UploadFile,
    kind: Literal["kug", "load", "term_load"],
    auth=Depends(identity),
    db=Depends(db_session),
):
    raw = file.file.read(settings.upload_limit_mb * 1024 * 1024 + 1)
    if len(raw) > settings.upload_limit_mb * 1024 * 1024:
        raise RuleError("Файл превышает допустимый размер")
    filename = Path(file.filename or "document.xlsx").name[:300]
    suffix = ".docx" if kind == "term_load" else ".xlsx"
    if not filename.casefold().endswith(suffix):
        raise RuleError(f"Загрузите файл {suffix}")
    key = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(ImportDocument).where(ImportDocument.digest == key))
    if existing:
        if existing.preview["format"] != kind:
            raise RuleError("Этот файл уже загружен как документ другого типа")
        return {"id": existing.id, "preview": existing.preview, "duplicate": True}
    preview = {"kug": parse_kug, "load": parse_load, "term_load": parse_word_load}[
        kind
    ](raw, filename)
    document = ImportDocument(id=uid(), digest=key, filename=filename, preview=preview)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / f"{key}{suffix}").write_bytes(raw)
    db.add(document)
    db.commit()
    return {"id": document.id, "preview": preview, "duplicate": False}


@app.get("/api/imports")
def imports(auth=Depends(identity), db=Depends(db_session)):
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "kind": d.preview["format"],
            "at": d.at.isoformat(),
        }
        for d in db.scalars(select(ImportDocument).order_by(ImportDocument.at.desc()))
    ]


@app.get("/api/imports/{doc_id}")
def import_preview(doc_id: str, auth=Depends(identity), db=Depends(db_session)):
    doc = db.get(ImportDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    return {"id": doc.id, "preview": doc.preview}


@app.get("/api/imports/{doc_id}/original")
def original(doc_id: str, auth=Depends(identity), db=Depends(db_session)):
    doc = db.get(ImportDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    suffix = ".docx" if doc.preview["format"] == "term_load" else ".xlsx"
    return FileResponse(
        settings.data_dir / f"{doc.digest}{suffix}", filename=doc.filename
    )


@app.post("/api/imports/{doc_id}/kug")
def confirm_kug(
    doc_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)
):
    doc = db.get(ImportDocument, doc_id)
    if doc is None or doc.preview["format"] != "kug":
        raise HTTPException(404, "КУГ не найден")
    item = body.item
    if not item.get("acknowledged"):
        raise RuleError("Подтвердите календарные даты и привязку к группам")
    sheet = next(
        (x for x in doc.preview["sheets"] if x["key"] == item.get("sheet_key")), None
    )
    if sheet is None:
        raise RuleError("Лист не найден")
    week = parse_week(item.get("week"))
    if not any(w["key"] == item.get("week_key") for w in sheet["weeks"]):
        raise RuleError("Столбец недели не найден")
    if any(e["week_key"] == item["week_key"] for e in sheet.get("errors", [])):
        raise RuleError(
            "В выбранной неделе есть непрочитанные или неверные часы. Исправьте исходный Excel и загрузите его заново"
        )
    groups = item.get("group_ids", [])
    if not groups:
        raise RuleError("Выберите учебные группы")
    selected = {r["row_key"]: r for r in item.get("rows", [])}
    rows = [r for r in sheet["rows"] if r["hours"].get(item["week_key"], 0)]
    if not rows:
        raise RuleError("В выбранном столбце нет часов")
    expected = {r["key"] for r in rows}
    if set(selected) != expected:
        raise RuleError(
            "Нужно сопоставить каждую строку выбранной недели, включая самостоятельную работу"
        )

    def change(s):
        plan_key = f"{doc_id}:{sheet['key']}:{item['week_key']}:{week}:{','.join(sorted(groups))}"
        if plan_key in s.plans:
            raise RuleError(
                "Эта неделя КУГ для этих групп уже подтверждена. Изменяйте существующую нагрузку"
            )
        for g in groups:
            if g not in s.groups:
                raise RuleError("Группа не найдена")
        for row in rows:
            mapping = selected[row["key"]]
            kind = mapping.get("kind", row["kind"])
            allocated = mapping.get("allocations", [])
            definitions = []
            if allocated:
                coverage = {g: 0 for g in leaf_groups(s, groups)}
                seen_allocations = set()
                for selected_allocation in allocated:
                    aid = selected_allocation.get("allocation_id")
                    a = s.allocations.get(aid)
                    if a is None or aid in seen_allocations or a.kind != kind:
                        raise RuleError(
                            "Выберите разные семестровые записи нужного вида"
                        )
                    seen_allocations.add(aid)
                    hours = selected_allocation.get(
                        "hours", row["hours"][item["week_key"]]
                    )
                    if (
                        not isinstance(hours, int)
                        or isinstance(hours, bool)
                        or hours < 1
                    ):
                        raise RuleError(
                            "Укажите целые положительные недельные часы для каждого назначения"
                        )
                    leaves = leaf_groups(s, a.group_ids)
                    if not leaves <= coverage.keys():
                        raise RuleError(
                            "Семестровое назначение включает группы вне выбранного состава"
                        )
                    for g in leaves:
                        coverage[g] += hours
                    definitions.append(
                        dict(
                            subject_id=a.subject_id,
                            group_ids=a.group_ids,
                            teacher_ids=a.teacher_ids,
                            teacher_mode=a.teacher_mode,
                            teacher_presence=a.teacher_presence,
                            allocation_id=a.id,
                            hours=hours,
                        )
                    )
                if any(h != row["hours"][item["week_key"]] for h in coverage.values()):
                    raise RuleError(
                        "Часы выбранных семестровых назначений должны точно закрывать строку КУГ для каждой группы"
                    )
            else:
                subject_id = mapping.get("subject_id")
                if not subject_id:
                    title = row["name"]
                    existing = [
                        x
                        for x in s.subjects.values()
                        if x.name == title and x.code == row["code"]
                    ]
                    subject = (
                        existing[0]
                        if existing
                        else Subject(name=title, code=row["code"])
                    )
                    s.subjects[subject.id] = subject
                    subject_id = subject.id
                participants = (
                    [groups] if mapping.get("joint") else [[g] for g in groups]
                )
                definitions = [
                    dict(
                        subject_id=subject_id,
                        group_ids=gs,
                        teacher_ids=mapping.get("teacher_ids", []),
                        teacher_mode=mapping.get("teacher_mode", "alternative"),
                        teacher_presence=mapping.get("teacher_presence", True),
                        hours=row["hours"][item["week_key"]],
                    )
                    for gs in participants
                ]
            for definition in definitions:
                source = f"{doc_id}:{sheet['key']}:{row['key']}:{item['week_key']}:{','.join(sorted(definition['group_ids']))}:{definition.get('allocation_id', '')}"
                if any(
                    r.week == week and r.source_ref == source
                    for r in s.requirements.values()
                ):
                    raise RuleError("Дублирующая строка импорта")
                req = Requirement(
                    **definition,
                    room_ids=mapping.get("room_ids", []),
                    week=week,
                    kind=kind,
                    block_hours=mapping.get("block_hours", 2),
                    source_ref=source,
                )
                if any(
                    r.week == week
                    and r.subject_id == req.subject_id
                    and r.kind == kind
                    and set(r.group_ids) == set(req.group_ids)
                    for r in s.requirements.values()
                ):
                    raise RuleError(
                        "Для этой дисциплины и группы уже есть нагрузка на неделю. Сверьте существующую запись"
                    )
                s.requirements[req.id] = req
        s.plans[plan_key] = {
            "document_id": doc_id,
            "sheet": sheet["name"],
            "week_label": next(
                x["label"] for x in sheet["weeks"] if x["key"] == item["week_key"]
            ),
            "week": str(week),
            "group_ids": groups,
            "rows": rows,
            "confirmed_at": now().isoformat(),
        }

    v, _ = mutate(db, body.version, auth[0].id, "Подтверждение недели КУГ", change)
    return {"version": v}


@app.put("/api/allocations/{item_id}")
def put_allocation(
    item_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)
):
    values = dict(body.item)
    update_linked = values.pop("update_linked", False)
    parsed = Allocation.model_validate({**values, "id": item_id})

    def change(s):
        s.allocations[item_id] = parsed
        if update_linked:
            linked = {
                r.id for r in s.requirements.values() if r.allocation_id == item_id
            }
            for rid in linked:
                r = s.requirements[rid]
                updates = {
                    key: getattr(parsed, key)
                    for key in (
                        "subject_id",
                        "group_ids",
                        "teacher_ids",
                        "teacher_mode",
                        "kind",
                        "teacher_presence",
                    )
                }
                s.requirements[rid] = Requirement.model_validate(
                    {**r.model_dump(), **updates}
                )
            for l in list(s.lessons.values()):
                if l.requirement_id not in linked:
                    continue
                if parsed.teacher_mode == "together":
                    l.teacher_ids = parsed.teacher_ids
                elif len(parsed.teacher_ids) == 1:
                    l.teacher_ids = parsed.teacher_ids
                elif not set(l.teacher_ids) <= set(parsed.teacher_ids):
                    raise RuleError(
                        "Для замены в существующем занятии укажите единственного преподавателя или сохраните его текущего преподавателя в списке"
                    )
                updates = {
                    key: getattr(parsed, key)
                    for key in ("subject_id", "group_ids", "kind", "teacher_presence")
                }
                s.lessons[l.id] = Lesson.model_validate({**l.model_dump(), **updates})

    v, _ = mutate(
        db, body.version, auth[0].id, "Изменение семестровой нагрузки", change
    )
    return {"version": v}


@app.delete("/api/allocations/{item_id}")
def delete_allocation(
    item_id: str, version: int, auth=Depends(identity), db=Depends(db_session)
):
    def change(s):
        if item_id not in s.allocations:
            raise HTTPException(404, "Семестровая нагрузка не найдена")
        del s.allocations[item_id]

    v, _ = mutate(db, version, auth[0].id, "Удаление семестровой нагрузки", change)
    return {"version": v}


@app.post("/api/imports/{doc_id}/term-load")
def confirm_term_load(
    doc_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)
):
    doc = db.get(ImportDocument, doc_id)
    if doc is None or doc.preview["format"] != "term_load":
        raise HTTPException(404, "Семестровая нагрузка не найдена")
    item = body.item
    if not item.get("acknowledged"):
        raise RuleError(
            "Подтвердите проверку часов, групп, преподавателей и дат семестра"
        )
    source = {e["key"]: e for t in doc.preview["tables"] for e in t["entries"]}
    selected = item.get("entries", [])
    if not selected or len(selected) > 500:
        raise RuleError("Выберите от 1 до 500 ячеек нагрузки")

    def change(s):
        count = 0
        seen = set()

        def resolve(names, catalog, model):
            ids = []
            if not isinstance(names, list) or not names:
                raise RuleError("Укажите названия групп и преподавателей")
            for value in names:
                name = str(value).strip()
                if not name or name in [catalog[i].name for i in ids]:
                    raise RuleError("Названия не должны быть пустыми или повторяться")
                matches = [
                    x for x in catalog.values() if x.name.casefold() == name.casefold()
                ]
                if len(matches) > 1:
                    raise RuleError(f"«{name}»: неоднозначный справочник")
                if matches:
                    entry = matches[0]
                elif model is Group:
                    metadata = item.get("groups", {}).get(name)
                    if not isinstance(metadata, dict):
                        raise RuleError(
                            f"«{name}»: подтвердите программу, курс, базу и год набора новой группы"
                        )
                    if not metadata.get("program") or any(
                        metadata.get(k) is None
                        for k in ("course", "base", "entry_year")
                    ):
                        raise RuleError(
                            "Для новой группы обязательны программа, курс, база и год набора"
                        )
                    entry = Group.model_validate(
                        {
                            **{
                                k: v
                                for k, v in metadata.items()
                                if k not in ("id", "name")
                            },
                            "name": name,
                        }
                    )
                else:
                    entry = model(name=name)
                catalog[entry.id] = entry
                ids.append(entry.id)
            return ids

        for reviewed in selected:
            key = reviewed.get("key")
            if key not in source or key in seen:
                raise RuleError("Ячейка не найдена или выбрана повторно")
            seen.add(key)
            original = source[key]
            if (
                original["hours"] is None
                and len(str(reviewed.get("note", "")).strip()) < 5
            ):
                raise RuleError(
                    "Поясните решение по неоднозначным часам исходной ячейки"
                )
            for value in (item.get("start_date"), item.get("end_date")):
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    raise RuleError("Укажите подтверждённые даты семестра")
            source_ref = f"{doc_id}:{key}:{item['start_date']}:{item['end_date']}"
            if any(a.source_ref == source_ref for a in s.allocations.values()):
                raise RuleError(
                    "Эта ячейка на указанный период уже подтверждена. Редактируйте семестровую нагрузку"
                )
            assignments = reviewed.get("assignments", [])
            if not assignments:
                raise RuleError("Для каждой выбранной ячейки нужны назначения")
            title = str(reviewed.get("subject", original["subject"])).strip()
            sid = reviewed.get("subject_id")
            if sid:
                if sid not in s.subjects:
                    raise RuleError("Дисциплина не найдена")
            else:
                matches = [
                    x
                    for x in s.subjects.values()
                    if x.name.casefold() == title.casefold()
                ]
                if len(matches) > 1:
                    raise RuleError(
                        "Дисциплина неоднозначна: выберите запись справочника"
                    )
                subject = matches[0] if matches else Subject(name=title)
                s.subjects[subject.id] = subject
                sid = subject.id
            used_groups = set()
            for assignment in assignments:
                group_ids = resolve(assignment.get("groups"), s.groups, Group)
                teacher_ids = resolve(assignment.get("teachers"), s.teachers, Teacher)
                if used_groups.intersection(group_ids):
                    raise RuleError(
                        "Группа повторяется в одной ячейке. Разделите часы и виды нагрузки отдельными исходными ячейками"
                    )
                used_groups.update(group_ids)
                sets = (
                    [group_ids] if assignment.get("joint") else [[g] for g in group_ids]
                )
                for participants in sets:
                    a = Allocation(
                        subject_id=sid,
                        group_ids=participants,
                        teacher_ids=teacher_ids,
                        teacher_mode=assignment.get("teacher_mode", "alternative"),
                        teacher_presence=reviewed.get("teacher_presence", True),
                        kind=reviewed.get("kind", original["kind"]),
                        hours=reviewed.get("hours"),
                        start_date=item["start_date"],
                        end_date=item["end_date"],
                        period=item.get("period", ""),
                        source_ref=source_ref,
                        note=reviewed.get("note", ""),
                    )
                    if any(
                        x.subject_id == a.subject_id
                        and x.kind == a.kind
                        and set(x.group_ids) == set(a.group_ids)
                        and x.start_date <= a.end_date
                        and a.start_date <= x.end_date
                        for x in s.allocations.values()
                    ):
                        raise RuleError(
                            "У этих групп уже есть семестровая нагрузка по дисциплине и виду. Сверьте запись или уточните раздел дисциплины"
                        )
                    s.allocations[a.id] = a
                    count += 1
        return count

    v, count = mutate(
        db, body.version, auth[0].id, "Подтверждение семестровой нагрузки Word", change
    )
    return {"version": v, "count": count}


@app.post("/api/imports/{doc_id}/load")
def confirm_load(
    doc_id: str, body: Change, auth=Depends(identity), db=Depends(db_session)
):
    doc = db.get(ImportDocument, doc_id)
    if doc is None or doc.preview["format"] != "load":
        raise HTTPException(404, "Нагрузка не найдена")
    mapping = body.item.get("mapping", {})
    if doc.preview.get("errors"):
        raise RuleError(
            "В файле есть формулы без рассчитанных значений или ошибки Excel. Пересчитайте и сохраните файл в Excel"
        )
    if not all(
        mapping.get(x) is not None
        for x in ["subject", "teacher", "group", "room", "hours"]
    ):
        raise RuleError("Сопоставьте предмет, группу, преподавателя, помещение и часы")

    def change(s):
        count = 0
        seen = set()
        for line, row in enumerate(doc.preview["rows"], 2):

            def value(field, default=""):
                return (
                    row.get(str(mapping.get(field)), default)
                    if mapping.get(field) is not None
                    else default
                )

            def resolve(field, collection):
                names = [x.strip() for x in str(value(field)).split(";") if x.strip()]
                if not names:
                    raise RuleError(f"Строка {line}: пустое поле {field}")
                ids = []
                for name in names:
                    matches = [
                        x.id
                        for x in collection.values()
                        if x.name.casefold() == name.casefold()
                    ]
                    if len(matches) != 1:
                        raise RuleError(
                            f"Строка {line}: «{name}» не найдено однозначно в справочнике"
                        )
                    ids.append(matches[0])
                return ids

            subject = resolve("subject", s.subjects)
            if len(subject) != 1:
                raise RuleError(f"Строка {line}: нужен один предмет")
            try:
                raw_date = str(value("week", body.item.get("week", "")))[:10]
                week = date.fromisoformat(raw_date)
                hours = float(value("hours"))
                block = float(value("block_hours", 2))
                if not hours.is_integer() or not block.is_integer():
                    raise ValueError()
            except (ValueError, TypeError):
                raise RuleError(
                    f"Строка {line}: укажите дату понедельника и целые часы"
                )
            kind = str(value("kind", "theory")).strip()
            kind = {
                "теория": "theory",
                "практика": "practice",
                "консультация": "consultation",
                "аттестация": "assessment",
                "уп/пп": "training",
                "курсовая": "coursework",
                "самостоятельная работа": "self_study",
                "с/р": "self_study",
            }.get(kind.casefold(), kind)
            req = Requirement(
                subject_id=subject[0],
                group_ids=resolve("group", s.groups),
                teacher_ids=resolve("teacher", s.teachers),
                room_ids=(
                    []
                    if kind == "self_study" and not str(value("room", "")).strip()
                    else resolve("room", s.rooms)
                ),
                week=week,
                hours=int(hours),
                block_hours=int(block),
                kind=kind,
                source_ref=f"{doc_id}:row{line}",
            )
            matches = [
                r
                for r in s.requirements.values()
                if r.subject_id == req.subject_id
                and r.week == req.week
                and r.kind == req.kind
                and set(r.group_ids) == set(req.group_ids)
            ]
            key = (req.subject_id, req.week, req.kind, tuple(sorted(req.group_ids)))
            if key in seen:
                raise RuleError(
                    f"Строка {line}: повторяется одна и та же недельная нагрузка. Объедините допустимые альтернативы в одной строке"
                )
            seen.add(key)
            if len(matches) > 1:
                raise RuleError(f"Строка {line}: неоднозначная нагрузка")
            if matches:
                if matches[0].hours != req.hours:
                    raise RuleError(
                        f"Строка {line}: часы нагрузки ({req.hours}) отличаются от КУГ ({matches[0].hours})"
                    )
                req.id = matches[0].id
                req.source_ref = matches[0].source_ref
                req.allocation_id = matches[0].allocation_id
                req.teacher_mode = matches[0].teacher_mode
                req.teacher_presence = matches[0].teacher_presence
            s.requirements[req.id] = req
            count += 1
        return count

    v, count = mutate(
        db, body.version, auth[0].id, "Импорт преподавательской нагрузки", change
    )
    return {"version": v, "count": count}


@app.get("/api/templates/load.xlsx")
def template(auth=Depends(identity)):
    return Response(
        load_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=workload-template.xlsx"},
    )


@app.get("/api/export.xlsx")
def export(
    week: date, group_ids: str = "", auth=Depends(identity), db=Depends(db_session)
):
    _, s = read_state(db)
    return Response(
        export_schedule(s, week, [x for x in group_ids.split(",") if x]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=schedule-{week}.xlsx"},
    )


@app.post("/api/generations")
def generation(body: Change, auth=Depends(identity), db=Depends(db_session)):
    workspace = db.scalar(select(Workspace).where(Workspace.id == 1).with_for_update())
    if workspace is None:
        raise RuleError("Приложение не инициализировано")
    if workspace.version != body.version:
        raise StaleVersion("Данные изменились. Обновите страницу")
    current = State.model_validate(workspace.payload)
    validate(current)
    if not current.settings.confirmed:
        raise RuleError("Подтвердите учебные дни и расписание звонков в настройках")
    week = parse_week(body.item.get("week"))
    if week.weekday() != 0:
        raise RuleError("Выберите понедельник")
    groups = body.item.get("group_ids", [])
    if any(x not in current.groups for x in groups):
        raise RuleError("Группа не найдена")
    if db.scalar(
        select(GenerationJob).where(GenerationJob.status.in_(["queued", "running"]))
    ):
        raise RuleError("Уже идёт расчёт. Дождитесь его окончания")
    job = GenerationJob(
        id=uid(),
        user_id=auth[0].id,
        source_version=workspace.version,
        request={"week": str(week), "group_ids": groups},
        source=workspace.payload,
        status="queued",
    )
    db.add(job)
    db.commit()
    return {"id": job.id, "status": job.status}


@app.get("/api/generations/{job_id}")
def job_status(job_id: str, auth=Depends(identity), db=Depends(db_session)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Расчёт не найден")
    return {
        "id": job.id,
        "status": job.status,
        "source_version": job.source_version,
        "result": job.result,
    }


@app.post("/api/generations/{job_id}/apply")
def apply_generation(
    job_id: str, body: Lease, auth=Depends(identity), db=Depends(db_session)
):
    job = db.get(GenerationJob, job_id)
    if (
        job is None
        or job.status != "completed"
        or not job.result
        or job.result["status"] not in {"optimal", "feasible"}
    ):
        raise RuleError("Нет допустимого варианта для применения")
    if job.source_version != body.version:
        raise StaleVersion("После расчёта данные изменились. Сформируйте новый вариант")

    def change(s):
        selected = set(job.result["selected_requirement_ids"])
        s.lessons = {
            k: l
            for k, l in s.lessons.items()
            if l.requirement_id not in selected or l.locked
        }
        for raw in job.result["lessons"]:
            lesson = Lesson.model_validate(raw)
            s.lessons[lesson.id] = lesson
        job.status = "applied"

    v, _ = mutate(
        db, body.version, auth[0].id, "Применение автоматического расписания", change
    )
    return {"version": v}


dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Метод API не найден")
        return FileResponse(dist / "index.html")
