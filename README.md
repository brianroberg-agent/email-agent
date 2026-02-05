# Email Agent Server

A privacy-focused FastAPI server that wraps the Gmail API for use with AI agents. Email bodies never leave the local machine - only metadata and LLM-generated summaries are returned to calling agents.

## Architecture

```
Gmail Pub-Sub ─────────────────────────────────┐
                                               │
Claude Code (cloud, orchestrator)              │
    │                                          │
    │  structured HTTP endpoints (JSON)        │
    ▼                                          ▼
email_server.py (local FastAPI server, port 8081)
    │                        │                 │
    │ Proxy API (API key)    │ Local LLM       │ Cloud LLM (person detection)
    ▼                        ▼                 ▼
api-proxy (handles OAuth)   Qwen3-14B      novita.ai/OpenAI (metadata only)
    │
    │ Gmail API (OAuth)
    ▼
Gmail
```

**Privacy guarantee**: Email bodies are processed locally and never sent to cloud services. The calling agent only sees message IDs, dates, sender addresses, subject lines, snippets (~100 chars), labels, and LLM-generated summaries.

**Person detection**: When using Gmail Pub-Sub for automatic classification, only email metadata (sender, subject, snippet) is sent to the cloud LLM for person detection. Body text from emails identified as personal never leaves the local machine.

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
| `CLOUD_LLM_URL` | No | `https://api.novita.ai/v3/openai` | Cloud LLM endpoint (OpenAI-compatible) |
| `CLOUD_LLM_API_KEY` | No | - | API key for cloud LLM (required for Pub-Sub classification) |
| `CLOUD_LLM_MODEL` | No | `minimax/minimax-m2.1` | Cloud model for person detection |
| `SENDER_WHITELIST` | No | - | Comma-separated emails/domains always routed to local MLX |
| `QUEUE_DB_PATH` | No | `/app/data/classification.db` | SQLite database path for classification queue |
| `QUEUE_RETENTION_DAYS` | No | `7` | Days to retain processed queue entries |

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

## Automatic Classification (Gmail Pub-Sub)

The email agent can automatically classify incoming emails using Gmail Pub-Sub notifications. This feature routes emails based on whether they're from real people:

- **Personal emails** → Queued for local MLX classification (body never leaves local machine)
- **Non-personal emails** → Classified by cloud LLM (body is sent to cloud)

### POST /pubsub/webhook

Receives Gmail Pub-Sub push notifications. Configure Google Cloud Pub-Sub to push to this endpoint.

```bash
# Gmail Pub-Sub sends notifications like:
curl -X POST http://localhost:8081/pubsub/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "data": "eyJlbWFpbEFkZHJlc3MiOiJ1c2VyQGV4YW1wbGUuY29tIiwiaGlzdG9yeUlkIjoiMTIzNDU2In0=",
      "messageId": "123",
      "publishTime": "2026-02-05T10:00:00Z"
    },
    "subscription": "projects/myproject/subscriptions/gmail"
  }'
```

Response:
```json
{
  "success": true,
  "message_id": "123456",
  "action": "processing",
  "classification": {"queued_messages": 3}
}
```

### POST /classify/{message_id}

Manually trigger classification for a specific email. Useful for testing or reprocessing.

```bash
curl -X POST http://localhost:8081/classify/18d5a3b2c4e5f6a7
```

Response:
```json
{
  "success": true,
  "message_id": "18d5a3b2c4e5f6a7",
  "action": "queued_for_mlx",
  "is_person": true,
  "classification": null
}
```

Actions:
- `queued_for_mlx` - Email is from a person, queued for local processing
- `classified_cloud` - Email is non-personal, classified by cloud LLM
- `skipped` - Email already in queue

### GET /queue/status

Get classification queue statistics.

```bash
curl http://localhost:8081/queue/status
```

Response:
```json
{
  "pending": 5,
  "processed": 142,
  "failed": 2,
  "oldest_pending": "2026-02-05T09:30:00"
}
```

### GET /config/whitelist

Get the current sender whitelist.

```bash
curl http://localhost:8081/config/whitelist
```

Response:
```json
{
  "whitelist": ["mom@gmail.com", "@family.com"]
}
```

### POST /config/whitelist

Add a sender to the whitelist (session only - use `SENDER_WHITELIST` env var for persistence).

```bash
curl -X POST http://localhost:8081/config/whitelist \
  -H "Content-Type: application/json" \
  -d '{"sender_pattern": "@important-domain.com"}'
```

Response:
```json
{
  "success": true,
  "message": "Added '@important-domain.com' to whitelist",
  "whitelist": ["mom@gmail.com", "@family.com", "@important-domain.com"]
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

## Gmail Pub-Sub Setup Guide

This guide walks through setting up automatic email classification using Gmail Pub-Sub and Tailscale Funnel.

### Prerequisites

- Google Cloud project with Gmail API enabled
- Tailscale sidecar running alongside email-agent (see agent-stack docker-compose)
- Cloud LLM API key (e.g., from novita.ai)

---

### Step 1: Enable Tailscale Funnel

Tailscale Funnel exposes your local service to the public internet over HTTPS.

**1.1 Run Funnel command in the Tailscale sidecar:**

```bash
docker compose exec email-agent-tailscale tailscale funnel 8081
```

You'll see output like:
```
https://email-agent.your-tailnet.ts.net/
|-- proxy http://127.0.0.1:8081

Funnel started, serving HTTPS on the internet.
```

**1.2 Note your public URL:**

```
https://email-agent.YOUR-TAILNET-NAME.ts.net
```

**1.3 Test it works:**

From anywhere on the internet:
```bash
curl https://email-agent.YOUR-TAILNET-NAME.ts.net/health
# Should return: {"status":"ok","version":"2.1"}
```

> **Note:** Funnel requires your Tailscale account to have Funnel enabled. Check [Tailscale admin console](https://login.tailscale.com/admin/settings/features) under Features.

---

### Step 2: Create Google Cloud Pub/Sub Topic

**2.1 Go to [Google Cloud Console Pub/Sub](https://console.cloud.google.com/cloudpubsub/topic/list)**

**2.2 Create a topic:**

- Click "Create Topic"
- Topic ID: `gmail-notifications`
- Leave defaults, click "Create"

**2.3 Grant Gmail permission to publish:**

The Gmail API uses a specific service account to publish. Add it as a publisher:

- Click on your topic (`gmail-notifications`)
- Go to "Permissions" tab
- Click "Add Principal"
- Principal: `gmail-api-push@system.gserviceaccount.com`
- Role: `Pub/Sub Publisher`
- Click "Save"

---

### Step 3: Create Push Subscription

**3.1 In the topic page, click "Create Subscription"**

**3.2 Configure the subscription:**

| Field | Value |
|-------|-------|
| Subscription ID | `gmail-to-email-agent` |
| Delivery type | **Push** |
| Endpoint URL | `https://email-agent.YOUR-TAILNET-NAME.ts.net/pubsub/webhook` |
| Acknowledgement deadline | 60 seconds |
| Retry policy | Minimum: 10s, Maximum: 600s |

**3.3 Click "Create"**

---

### Step 4: Set Up Gmail Watch

Tell Gmail to send notifications to your Pub/Sub topic.

**4.1 Get your topic name:**

```
projects/YOUR-PROJECT-ID/topics/gmail-notifications
```

**4.2 Call the Gmail watch API:**

Using the [Gmail API Explorer](https://developers.google.com/gmail/api/reference/rest/v1/users/watch):

1. Go to the link above
2. Click "Try it"
3. Set `userId` to `me`
4. In Request body:
   ```json
   {
     "topicName": "projects/YOUR-PROJECT-ID/topics/gmail-notifications",
     "labelIds": ["INBOX"]
   }
   ```
5. Click "Execute" and authorize with your Gmail account

**Response:**
```json
{
  "historyId": "1234567",
  "expiration": "1707300000000"
}
```

> **Important:** Gmail watch expires after 7 days. You'll need to renew it periodically.

---

### Step 5: Create Gmail Labels

Create the classification labels in Gmail:

1. Go to Gmail → Settings → Labels
2. Create label: `agent/cloud`
3. Create label: `agent/local`

---

### Step 6: Configure Environment Variables

Update your `.env` file:

```bash
# Cloud LLM for person detection
CLOUD_LLM_URL=https://api.novita.ai/v3/openai
CLOUD_LLM_API_KEY=your_novita_api_key
CLOUD_LLM_MODEL=minimax/minimax-m2.1

# Sender whitelist (emails from these always go to local MLX)
SENDER_WHITELIST=mom@gmail.com,spouse@gmail.com,@family-domain.com
```

Restart the email-agent:
```bash
docker compose up -d email-agent
```

---

### Step 7: Test the Setup

**7.1 Check queue status:**
```bash
curl https://email-agent.YOUR-TAILNET-NAME.ts.net/queue/status
```

**7.2 Send yourself a test email**

**7.3 Check the logs:**
```bash
docker compose logs -f email-agent
```

You should see:
```
INFO: Pub-Sub notification: email=you@gmail.com, history=1234567
INFO: Classified email abc123 via cloud (or queued for MLX)
```

**7.4 Manually test classification:**
```bash
curl -X POST https://email-agent.YOUR-TAILNET-NAME.ts.net/classify/MESSAGE_ID
```

---

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Funnel not working | Run `docker compose exec email-agent-tailscale tailscale funnel status` |
| Pub/Sub not delivering | Check subscription metrics in Cloud Console, verify endpoint URL |
| "History expired" errors | Normal if historyId is old; fresh notifications will work |
| Labels not applying | Ensure labels `agent/cloud` and `agent/local` exist in Gmail |
| Cloud LLM errors | Check `CLOUD_LLM_API_KEY` is set correctly |

---

### Renewing Gmail Watch

Gmail watch expires after 7 days. Renew via the API Explorer or add to your maintenance tasks.

---

## License

MIT
