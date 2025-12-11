# Agent Integration Guide

How AI agents can integrate with the feedback system for automated triage and resolution.

## Overview

The UI Feedback API is designed to be **token-efficient** and **agent-friendly**. Agents can:

1. **List and triage** - Get open tickets with minimal context
2. **Get details progressively** - Fetch full context only when needed  
3. **Update status** - Mark tickets as in-progress or resolved
4. **Search and filter** - Find relevant tickets efficiently

## Quick Start for Agents

### 1. Get Open Tickets (Minimal Context)

```bash
curl "http://localhost:8001/api/feedback?status=open&limit=10"
```

Response (token-efficient summary):
```json
{
  "items": [
    {
      "id": "abc-123",
      "url": "http://app.com/dashboard",
      "component_name": "MetricCard",
      "feedback_type": "bug",
      "comment": "Chart not loading",
      "priority": "high",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 15,
  "page": 1
}
```

### 2. Claim a Ticket (Mark In Progress)

```bash
curl -X PATCH "http://localhost:8001/api/feedback/abc-123" \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress", "assigned_to": "agent:claude"}'
```

### 3. Get Full Details (When Needed)

```bash
curl "http://localhost:8001/api/feedback/abc-123"
```

Response (full context):
```json
{
  "id": "abc-123",
  "url": "http://app.com/dashboard",
  "route": "/dashboard",
  "viewport_width": 1920,
  "viewport_height": 1080,
  "click_x": 450,
  "click_y": 320,
  "css_selector": "#root > div > main > div.metrics > div:nth-child(1)",
  "xpath": "//*[@id='root']/div/main/div[2]/div[1]",
  "component_name": "MetricCard",
  "feedback_type": "bug",
  "comment": "Chart not loading after page refresh",
  "status": "in_progress",
  "priority": "high",
  "assigned_to": "agent:claude",
  "app_name": "aef-dashboard",
  "app_version": "0.1.0",
  "environment": "development",
  "git_commit": "a1b2c3d",
  "git_branch": "main",
  "hostname": "localhost",
  "user_agent": "Mozilla/5.0...",
  "created_at": "2024-01-15T10:30:00Z",
  "media": [
    {
      "id": "media-456",
      "media_type": "screenshot",
      "mime_type": "image/png",
      "file_size": 45678
    }
  ]
}
```

### 4. Mark Resolved

```bash
curl -X PATCH "http://localhost:8001/api/feedback/abc-123" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "resolved",
    "resolution_notes": "Fixed chart loading issue in commit e4f5g6h"
  }'
```

## Progressive Disclosure Strategy

To minimize token usage, use a tiered approach:

### Tier 1: Summary List (Low Tokens)
```bash
GET /api/feedback?status=open&limit=20
```
Returns: id, url, component_name, comment (truncated), priority, created_at

### Tier 2: Single Ticket Details (Medium Tokens)
```bash
GET /api/feedback/{id}
```
Returns: Full ticket with location context, selectors, environment info

### Tier 3: Media Content (High Tokens)
```bash
GET /api/media/{media_id}/content
```
Returns: Base64 screenshot or audio (use sparingly)

## Recommended Agent Workflow

```python
# 1. Get overview stats
stats = api.get("/feedback/stats")
print(f"Open: {stats['by_status']['open']}, Critical: {stats['by_priority']['critical']}")

# 2. Prioritize critical/high tickets
tickets = api.get("/feedback?status=open&priority=critical,high&limit=5")

# 3. For each ticket, decide if agent can help
for ticket in tickets['items']:
    if can_handle(ticket['component_name'], ticket['comment']):
        # Claim it
        api.patch(f"/feedback/{ticket['id']}", {
            "status": "in_progress",
            "assigned_to": "agent:my-agent"
        })
        
        # Get full context only if needed
        if needs_more_context(ticket):
            details = api.get(f"/feedback/{ticket['id']}")
            
        # Work on the issue...
        
        # Mark resolved
        api.patch(f"/feedback/{ticket['id']}", {
            "status": "resolved",
            "resolution_notes": "Fixed by agent in PR #123"
        })
```

## API Reference

### List Feedback
```
GET /api/feedback
```

Query Parameters:
| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter: open, in_progress, resolved, closed, wont_fix |
| `priority` | string | Filter: low, medium, high, critical |
| `type` | string | Filter: bug, feature, ui_ux, performance, question, other |
| `app` | string | Filter by app_name |
| `search` | string | Search in comments |
| `page` | int | Page number (default: 1) |
| `limit` | int | Items per page (default: 50, max: 100) |
| `desc` | bool | Order descending (default: true) |

### Get Ticket
```
GET /api/feedback/{id}
```

Returns full ticket with media metadata.

### Update Ticket
```
PATCH /api/feedback/{id}
```

Body (all optional):
```json
{
  "status": "in_progress",
  "priority": "high",
  "assigned_to": "agent:my-agent",
  "resolution_notes": "string"
}
```

### Get Stats
```
GET /api/feedback/stats?app=my-app
```

Returns aggregate counts by status, type, priority, app.

## Best Practices for Agents

### 1. Be a Good Citizen
- Only claim tickets you can actually work on
- Update status promptly
- Add meaningful resolution notes

### 2. Use Filters Aggressively
```bash
# Only bugs in your component
?status=open&type=bug&search=MetricCard
```

### 3. Batch Operations
Get multiple tickets in one request instead of fetching one at a time.

### 4. Preserve Context
Include ticket ID and summary in your work context:
```
Working on feedback abc-123: "Chart not loading in MetricCard"
```

### 5. Link to Fixes
In resolution_notes, include:
- PR/commit links
- What was changed
- How to verify

## Future Considerations

### Webhooks (Planned)
Subscribe to new feedback events:
```json
{
  "url": "https://your-agent/webhook",
  "events": ["feedback.created", "feedback.updated"]
}
```

### Batch API (Planned)
Update multiple tickets at once:
```bash
POST /api/feedback/batch
{
  "ids": ["abc-123", "def-456"],
  "update": {"status": "in_progress"}
}
```

### Agent Handoff (Planned)
Pass context between agents:
```json
{
  "handoff_to": "agent:specialist",
  "handoff_notes": "Needs database expertise"
}
```

## Example: MCP Tool Integration

For agents using Model Context Protocol:

```json
{
  "name": "feedback_list",
  "description": "List open feedback tickets",
  "parameters": {
    "status": "open",
    "priority": "high,critical",
    "limit": 10
  }
}
```

```json
{
  "name": "feedback_claim",
  "description": "Claim a ticket to work on",
  "parameters": {
    "ticket_id": "abc-123"
  }
}
```

```json
{
  "name": "feedback_resolve",
  "description": "Mark a ticket as resolved",
  "parameters": {
    "ticket_id": "abc-123",
    "notes": "Fixed in commit xyz"
  }
}
```
