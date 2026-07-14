FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini main.py ./
COPY alembic ./alembic
COPY waterbot ./waterbot

FROM base AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q"]

# Keep the production runtime as the final stage so platforms such as Railway
# select it when they build the Dockerfile without an explicit target.
FROM base AS runtime

RUN groupadd --system waterbot \
    && useradd --system --gid waterbot --home-dir /app waterbot \
    && chown -R waterbot:waterbot /app

USER waterbot
CMD ["python", "main.py"]
