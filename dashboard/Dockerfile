# querychat taxi dashboard, linux/arm64 (Fargate ARM64)
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
# libsass (via shinychat) has no aarch64 wheel: build it here, not in the runtime image
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY app.py traces.py ./
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
# the S3 extensions, installed now so the task does not download them at start (the data comes from S3 at start)
RUN python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs'); c.execute('INSTALL aws'); c.execute('LOAD httpfs'); c.execute('LOAD aws')"
EXPOSE 8000
CMD ["shiny", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
