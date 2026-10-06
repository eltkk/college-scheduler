FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install -r requirements.lock && useradd --create-home --uid 10001 scheduler
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY deploy/start.sh ./deploy/start.sh
COPY --from=frontend /build/dist ./frontend/dist
RUN mkdir -p /app/data && chown -R scheduler:scheduler /app && chmod +x /app/deploy/start.sh
USER scheduler
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["/app/deploy/start.sh"]
