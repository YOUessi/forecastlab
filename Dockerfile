# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORECASTLAB_DATA_DIR=/app/data
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist/ ./frontend/dist/
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.api:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
