# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN python -m venv /venv && /venv/bin/pip install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/venv/bin:$PATH"
RUN groupadd --system --gid 10001 schnaeppli && useradd --system --uid 10001 --gid schnaeppli --home /app schnaeppli
WORKDIR /app
COPY --from=build /venv /venv
COPY --chown=schnaeppli:schnaeppli app ./app
COPY --chown=schnaeppli:schnaeppli migrations ./migrations
COPY --chown=schnaeppli:schnaeppli alembic.ini ./
USER schnaeppli
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
