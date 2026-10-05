FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./backend
COPY config ./config
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/backend" PYTHONUNBUFFERED=1
RUN useradd --create-home meditron
USER meditron
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
