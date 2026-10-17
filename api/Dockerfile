# Cloud Run image for the mirava.ai REST API (build context: repo root).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY shared ./shared
COPY api ./api
COPY world ./world
COPY config ./config
COPY assets/maps ./assets/maps
ENV PATH="/app/.venv/bin:$PATH" ENV=cloud
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
