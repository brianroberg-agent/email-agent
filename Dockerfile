FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY *.py ./

EXPOSE 8081

CMD ["uv", "run", "uvicorn", "email_server:app", "--host", "0.0.0.0", "--port", "8081"]
