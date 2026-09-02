# Development image: hot-reload via --reload + a bind-mounted source tree
# (see docker-compose.yml), not a production build. No multi-stage/slim
# optimization yet — not worth it before this ever needs to actually
# deploy (Section 10: don't build for hypothetical future requirements).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
