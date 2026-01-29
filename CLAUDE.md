# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

## Project Overview

This is an email agent server - a privacy-focused FastAPI wrapper around the Gmail API. Email bodies never leave the local machine; only metadata and LLM-generated summaries are returned to calling agents.

## Package Management

Use `uv` for package management. Dependencies are defined in `pyproject.toml`.

```bash
# Run the server (uv handles dependencies automatically)
uv run uvicorn email_server:app --port 8081

# Run tests (includes dev dependencies)
uv run --extra dev pytest tests/ -v

# Add a new dependency: edit pyproject.toml, then uv will install it on next run
```

## Running Tests

```bash
uv run --extra dev pytest tests/ -v
```

The test suite uses mocked Gmail API and LLM responses - no credentials required.

## Project Structure

- `email_server.py` - Main FastAPI application with all endpoints
- `gmail_utils.py` - Gmail API utilities (auth, header extraction, body decoding)
- `tests/` - Test suite
  - `conftest.py` - Shared fixtures and sample data
  - `test_email_server.py` - Endpoint and utility tests
  - `test_readme_documentation.py` - Verifies all endpoints are documented in README
- `pyproject.toml` - Project metadata and dependencies

## Key Design Decisions

1. **Privacy**: Email bodies are processed locally via a local LLM (Qwen3-14B). The calling agent only sees metadata and summaries.

2. **No agent loop**: Unlike the previous version, this server has no internal agent loop. The calling agent (Claude) makes all orchestration decisions.

3. **Structured endpoints**: Each operation has a dedicated endpoint rather than a single natural-language endpoint.

## API Endpoints

- `GET /health` - Health check
- `POST /search` - Search emails with structured filters (returns from_name, has_attachments)
- `POST /summarize` - Summarize an email (uses local LLM)
- `POST /ask-about` - Ask a question about an email (uses local LLM)
- `POST /mark-read` - Mark email as read
- `POST /apply-label` - Apply a label to an email
- `POST /archive` - Archive an email
- `POST /batch-summarize` - Summarize multiple emails with triage info (detected_action, detected_deadline)
- `POST /bulk-actions` - Apply multiple operations to multiple emails

## Environment Variables

- `MLX_URL` - Local LLM endpoint (default: `http://localhost:8080/v1/chat/completions`)
- `MLX_MODEL` - Model name (default: `qwen/qwen3-14b`)
