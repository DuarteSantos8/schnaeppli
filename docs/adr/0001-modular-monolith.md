# ADR 0001: Modular monolith with a separate worker

**Decision.** One Python backend, run as an API process and an arq worker, sharing
models and services. No microservices.

**Why.** A self-hosted app for one person or a household must be easy to run and
upgrade. Search, analysis and digests need to be independent *jobs*, not separate
*services*. arq (async, Redis-backed, built-in cron) fits an async FastAPI codebase
with much less machinery than Celery.
