import logging
import signal
import time
from datetime import date, timedelta
from sqlalchemy import select
from .config import settings
from .db import GenerationJob, SessionLocal, now
from .domain import State
from .scheduler import generate
from .validation import RuleError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scheduler.worker")


def deadline(signum, frame):
    raise TimeoutError("Превышен общий лимит расчёта")


def run_once():
    with SessionLocal() as db:
        cutoff = now() - timedelta(seconds=settings.solver_seconds + 180)
        abandoned = db.scalars(
            select(GenerationJob)
            .where(GenerationJob.status == "running", GenerationJob.started < cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        for job in abandoned:
            job.status = "failed"
            job.finished = now()
            job.result = {
                "status": "timeout",
                "message": "Рабочий процесс остановился. Запустите расчёт повторно",
                "lessons": [],
            }
            job.source = {}
        job = db.scalar(
            select(GenerationJob)
            .where(GenerationJob.status == "queued")
            .order_by(GenerationJob.created)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            db.commit()
            return False
        job.status = "running"
        job.started = now()
        db.commit()
        job_id = job.id
        source = job.source
        request = job.request
    try:
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(settings.solver_seconds + 90)
        result = generate(
            State.model_validate(source),
            date.fromisoformat(request["week"]),
            request["group_ids"],
        )
        status = "completed"
    except TimeoutError as exc:
        result = {"status": "timeout", "message": str(exc), "lessons": []}
        status = "failed"
    except RuleError as exc:
        result = {
            "status": "invalid",
            "message": "; ".join(exc.messages),
            "lessons": [],
        }
        status = "failed"
    except Exception:
        log.exception("Generation job failed: %s", job_id)
        result = {
            "status": "invalid",
            "message": "Расчёт остановился из-за технической ошибки. Исходное расписание сохранено",
            "lessons": [],
        }
        status = "failed"
    finally:
        signal.alarm(0)
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        job.result = result
        # Only queued/running calculations need their full source snapshot.
        job.source = {}
        job.status = status
        job.finished = now()
        db.commit()
    return True


def main():
    while True:
        try:
            if not run_once():
                time.sleep(1)
        except Exception:
            log.exception("Worker loop failed")
            time.sleep(5)


if __name__ == "__main__":
    main()
