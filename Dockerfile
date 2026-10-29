FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY sql ./sql
RUN uv sync --frozen --no-dev
CMD ["uv", "run", "--no-sync", "uvicorn", "tnt.api:app", "--host", "0.0.0.0", "--port", "8000"]
