# Email Agent Server

A privacy-focused FastAPI server that wraps the Gmail API for use with AI agents. Email bodies never leave the local machine - only metadata and LLM-generated summaries are returned to calling agents.

## Architecture

```
Claude Code (cloud, orchestrator)
    │
    │  structured HTTP endpoints (JSON)
    ▼
email_server.py (local FastAPI server, port 8081)
    │                        │
    │ Gmail API (OAuth)      │ Local LLM (MLX, port 8080)
    ▼                        ▼
Gmail                   Qwen3-14B (summarize/ask-about only)
```

**Privacy guarantee**: Email bodies are processed locally and never sent to cloud services. The calling agent only sees message IDs, dates, sender addresses, subject lines, snippets (~100 chars), labels, and LLM-generated summaries.

## Installation

No separate install step needed. The `uv run` command automatically manages dependencies.

### Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- Gmail OAuth credentials (`token.json`)
- Local LLM server (optional, for `/summarize` and `/ask-about` endpoints)

## Usage

Start the server:

```bash
uv run uvicorn email_server:app --host 0.0.0.0 --port 8081
```

The server must be started from the directory containing `token.json`.

## API Endpoints

### GET /health

Health check endpoint. No Gmail or LLM dependency.

```bash
curl http://localhost:8081/health
```

Response:
```json
{"status": "ok", "version": "2.0"}
```

### POST /search

Search Gmail with structured parameters. Returns message metadata including snippets.

```bash
curl -X POST http://localhost:8081/search \
  -H "Content-Type: application/json" \
  -d '{"from_addr": "sender@example.com", "limit": 5}'
```

Request body:
| Field | Type | Description |
|-------|------|-------------|
| `from_addr` | string | Filter by sender (maps to Gmail `from:` query) |
| `to_addr` | string | Filter by recipient (maps to `to:` query) |
| `subject` | string | Filter by subject (maps to `subject:` query) |
| `query` | string | Raw Gmail query syntax (appended to other filters) |
| `folder` | string | Label/folder to search in (e.g., `INBOX`) |
| `since` | string | Search after date (format: `YYYY/MM/DD`) |
| `before` | string | Search before date (format: `YYYY/MM/DD`) |
| `limit` | integer | Max results (default 10, max 50) |

Response:
```json
{
  "success": true,
  "messages": [
    {
      "id": "18d5a3b2c4e5f6a7",
      "date": "Jan 25, 2026 3:42 PM",
      "from_addr": "Sender Name <sender@example.com>",
      "from_name": "Sender Name",
      "subject": "Re: Topic",
      "snippet": "Thanks for reaching out...",
      "labels": ["INBOX", "UNREAD"],
      "has_attachments": false
    }
  ],
  "error": null
}
```

### POST /summarize

Summarize a specific email using the local LLM. The raw email body is never returned.

```bash
curl -X POST http://localhost:8081/summarize \
  -H "Content-Type: application/json" \
  -d '{"message_id": "18d5a3b2c4e5f6a7"}'
```

Response:
```json
{
  "success": true,
  "answer": "The sender is thanking you for the conversation and mentions being available next month.",
  "error": null
}
```

### POST /ask-about

Ask a specific question about an email using the local LLM.

```bash
curl -X POST http://localhost:8081/ask-about \
  -H "Content-Type: application/json" \
  -d '{"message_id": "18d5a3b2c4e5f6a7", "question": "Did they mention a deadline?"}'
```

Response:
```json
{
  "success": true,
  "answer": "No, the sender did not mention a specific deadline.",
  "error": null
}
```

### POST /mark-read

Mark an email as read by removing the UNREAD label.

```bash
curl -X POST http://localhost:8081/mark-read \
  -H "Content-Type: application/json" \
  -d '{"email_id": "18d5a3b2c4e5f6a7"}'
```

Response:
```json
{"success": true, "message": "Email marked as read"}
```

### POST /apply-label

Apply a label to an email.

```bash
curl -X POST http://localhost:8081/apply-label \
  -H "Content-Type: application/json" \
  -d '{"email_id": "18d5a3b2c4e5f6a7", "label_name": "STARRED"}'
```

Response:
```json
{"success": true, "message": "Label 'STARRED' applied"}
```

### POST /archive

Archive an email by removing it from the inbox.

```bash
curl -X POST http://localhost:8081/archive \
  -H "Content-Type: application/json" \
  -d '{"email_id": "18d5a3b2c4e5f6a7"}'
```

Response:
```json
{"success": true, "message": "Email archived"}
```

### POST /batch-summarize

Summarize multiple emails with triage information. Processes emails sequentially and returns structured data including detected action types and deadlines.

```bash
curl -X POST http://localhost:8081/batch-summarize \
  -H "Content-Type: application/json" \
  -d '{"message_ids": ["18d5a3b2c4e5f6a7", "18d5a3b2c4e5f6a8"]}'
```

Response:
```json
{
  "success": true,
  "results": [
    {
      "message_id": "18d5a3b2c4e5f6a7",
      "success": true,
      "summary": "John is requesting a review of the Q4 report by Friday.",
      "detected_action": "review_requested",
      "detected_deadline": "2026-02-01",
      "error": null
    },
    {
      "message_id": "18d5a3b2c4e5f6a8",
      "success": true,
      "summary": "Weekly newsletter with company updates.",
      "detected_action": "info_only",
      "detected_deadline": null,
      "error": null
    }
  ],
  "error": null
}
```

Detected action types:
| Action | Description |
|--------|-------------|
| `review_requested` | Someone is asking you to review something |
| `meeting_request` | Calendar invite or meeting scheduling |
| `info_only` | FYI, newsletter, or informational update |
| `action_required` | Explicit request for you to do something |
| `approval_needed` | Waiting for your approval or sign-off |
| `question` | Someone is asking you a question |
| `follow_up` | Following up on a previous conversation |
| `deadline` | Contains a deadline or time-sensitive request |

### POST /bulk-actions

Apply multiple operations to multiple emails. Always returns 200 with per-email results for easy client handling.

```bash
curl -X POST http://localhost:8081/bulk-actions \
  -H "Content-Type: application/json" \
  -d '{"email_ids": ["18d5a3b2c4e5f6a7", "18d5a3b2c4e5f6a8"], "operations": ["mark_read", "apply_label:PROCESSED"]}'
```

Request body:
| Field | Type | Description |
|-------|------|-------------|
| `email_ids` | string[] | List of email IDs to act on |
| `operations` | string[] | Operations to apply (see below) |

Supported operations:
- `mark_read` - Remove UNREAD label
- `archive` - Remove INBOX label
- `apply_label:LABEL_NAME` - Add the specified label (e.g., `apply_label:IMPORTANT`)

Response:
```json
{
  "success": true,
  "results": [
    {"email_id": "18d5a3b2c4e5f6a7", "success": true, "error": null},
    {"email_id": "18d5a3b2c4e5f6a8", "success": true, "error": null}
  ],
  "success_count": 2,
  "error_count": 0,
  "error": null
}
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MLX_URL` | `http://localhost:8080/v1/chat/completions` | Local LLM endpoint |
| `MLX_MODEL` | `qwen/qwen3-14b` | Model name for LLM requests |

## Gmail OAuth Setup

1. Create a Google Cloud project and enable the Gmail API
2. Create OAuth 2.0 credentials (Desktop app type)
3. Download the credentials and run the OAuth flow to generate `token.json`
4. Place `token.json` in the project directory

**Note**: Do not commit `token.json` to version control.

## Development

Run tests:

```bash
uv run --extra dev pytest tests/ -v
```

The test suite uses mocked Gmail API and LLM responses - no credentials required.

## License

MIT
