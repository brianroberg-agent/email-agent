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
    │ Proxy API (API key)    │ Local LLM (MLX, port 8080)
    ▼                        ▼
api-proxy (handles OAuth)   Qwen3-14B (summarize/ask-about only)
    │
    │ Gmail API (OAuth)
    ▼
Gmail
```

**Privacy guarantee**: Email bodies are processed locally and never sent to cloud services. The calling agent only sees message IDs, dates, sender addresses, subject lines, snippets (~100 chars), labels, and LLM-generated summaries.

**Human-in-the-loop**: The proxy server handles all confirmation flows for write operations. Dangerous operations (sending email, drafts) are blocked at the proxy level.

## Installation

No separate install step needed. The `uv run` command automatically manages dependencies.

### Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- Access to an [api-proxy](https://github.com/brianroberg/api-proxy) server with a valid API key
- Local LLM server (optional, for `/summarize` and `/ask-about` endpoints)

## Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your proxy API key:
   ```
   PROXY_API_KEY=aproxy_your_api_key_here
   ```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROXY_API_KEY` | Yes | - | API key for proxy authentication (format: `aproxy_...`) |
| `PROXY_URL` | No | `http://host.docker.internal:8000` | URL of the proxy server |
| `MLX_URL` | No | `http://localhost:8080/v1/chat/completions` | Local LLM endpoint |
| `MLX_MODEL` | No | `qwen/qwen3-14b` | Model name for LLM requests |

## Usage

Start the server:

```bash
uv run uvicorn email_server:app --host 0.0.0.0 --port 8081
```

Ensure the proxy server is running and accessible at the configured `PROXY_URL`.

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

### GET /labels

List all available Gmail labels with message counts.

```bash
curl http://localhost:8081/labels
```

Response:
```json
{
  "success": true,
  "labels": [
    {
      "id": "INBOX",
      "name": "INBOX",
      "type": "system",
      "messages_total": 150,
      "messages_unread": 5
    },
    {
      "id": "Label_123",
      "name": "Work",
      "type": "user",
      "messages_total": 42,
      "messages_unread": 3
    }
  ],
  "error": null
}
```

Note: `messages_total` and `messages_unread` may be `null` for some labels when counts are unavailable.

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

Apply per-email operations in a single request. Each email can have different operations. Always returns 200 with per-email results for easy client handling.

```bash
curl -X POST http://localhost:8081/bulk-actions \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {"email_id": "18d5a3b2c4e5f6a7", "operations": ["mark_read"]},
      {"email_id": "18d5a3b2c4e5f6a8", "operations": ["mark_read", "archive"]},
      {"email_id": "18d5a3b2c4e5f6a9", "operations": ["mark_read", "apply_label:IMPORTANT"]}
    ]
  }'
```

Request body:
| Field | Type | Description |
|-------|------|-------------|
| `actions` | object[] | List of per-email actions |
| `actions[].email_id` | string | Email ID to act on |
| `actions[].operations` | string[] | Operations to apply to this email |

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
    {"email_id": "18d5a3b2c4e5f6a8", "success": true, "error": null},
    {"email_id": "18d5a3b2c4e5f6a9", "success": true, "error": null}
  ],
  "success_count": 3,
  "error_count": 0,
  "error": null
}
```

## Proxy Server

This server requires access to an [api-proxy](https://github.com/brianroberg/api-proxy) instance that handles Gmail OAuth and human-in-the-loop controls.

### Allowed Operations

The proxy permits these Gmail API operations:
- List and retrieve messages
- List and retrieve labels
- Modify message labels (add/remove)
- Trash/untrash messages

### Blocked Operations

The proxy blocks these operations (returns 403 Forbidden):
- Sending email
- Creating, modifying, or sending drafts
- Importing or inserting messages

### Error Responses

When the proxy returns an error, endpoints return it in the response body:

```json
{
  "success": false,
  "error": "Authentication error: Invalid API key",
  "messages": []
}
```

Error prefixes indicate the type:
- `Authentication error:` - Invalid or missing API key (proxy returned 401)
- `Operation blocked:` - Operation not allowed or confirmation rejected (proxy returned 403)
- `Proxy error:` - Backend or server error (proxy returned 5xx)

## Development

Run tests:

```bash
uv run --extra dev pytest tests/ -v
```

The test suite uses mocked proxy client and LLM responses - no credentials required.

## License

MIT
