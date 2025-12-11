# Operations Guide

Managing feedback tickets and operating the feedback system.

## Ticket Lifecycle

```
┌──────┐    ┌─────────────┐    ┌──────────┐    ┌────────┐
│ Open │───▶│ In Progress │───▶│ Resolved │───▶│ Closed │
└──────┘    └─────────────┘    └──────────┘    └────────┘
    │                               │
    └───────────────────────────────┼──────▶ Won't Fix
                                    │
                                    └──────▶ Reopened → Open
```

### Status Definitions

| Status | Meaning |
|--------|---------|
| **Open** | New feedback, not yet triaged |
| **In Progress** | Being worked on |
| **Resolved** | Fix implemented, awaiting verification |
| **Closed** | Verified fixed or no longer relevant |
| **Won't Fix** | Intentional behavior or out of scope |

## Managing Tickets via UI

### Viewing Tickets
1. Click the feedback button → "View Tickets"
2. Use filters to narrow down: Open, In Progress, etc.
3. Click a ticket to see full details

### Changing Status
1. Use the dropdown next to each ticket
2. Status changes are saved immediately

### Triaging Workflow
1. Review new "Open" tickets daily
2. Set appropriate priority
3. Move to "In Progress" when starting work
4. Add resolution notes when done
5. Mark "Resolved" for user verification

## Managing Tickets via API

### List All Feedback

```bash
curl "http://localhost:8001/api/feedback"
```

### Filter by Status

```bash
curl "http://localhost:8001/api/feedback?status=open"
curl "http://localhost:8001/api/feedback?status=in_progress"
```

### Filter by App

```bash
curl "http://localhost:8001/api/feedback?app=my-app"
```

### Filter by Priority

```bash
curl "http://localhost:8001/api/feedback?priority=critical"
```

### Search Comments

```bash
curl "http://localhost:8001/api/feedback?search=login+button"
```

### Pagination

```bash
curl "http://localhost:8001/api/feedback?page=2&limit=20"
```

### Update a Ticket

```bash
curl -X PATCH "http://localhost:8001/api/feedback/{id}" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "in_progress",
    "assigned_to": "developer@example.com",
    "resolution_notes": "Investigating the issue"
  }'
```

### Get Statistics

```bash
curl "http://localhost:8001/api/feedback/stats"
```

Response:
```json
{
  "total": 42,
  "by_status": {
    "open": 15,
    "in_progress": 8,
    "resolved": 12,
    "closed": 5,
    "wont_fix": 2
  },
  "by_type": {
    "bug": 20,
    "feature": 10,
    "ui_ux": 8,
    "performance": 4,
    "question": 0,
    "other": 0
  },
  "by_priority": {
    "low": 5,
    "medium": 25,
    "high": 10,
    "critical": 2
  },
  "by_app": {
    "aef-dashboard": 30,
    "my-other-app": 12
  }
}
```

## Database Operations

### Backup

```bash
pg_dump $UI_FEEDBACK_DATABASE_URL > feedback_backup.sql
```

### Restore

```bash
psql $UI_FEEDBACK_DATABASE_URL < feedback_backup.sql
```

### Cleanup Old Tickets

```sql
-- Delete resolved tickets older than 90 days
DELETE FROM feedback_items 
WHERE status IN ('closed', 'wont_fix') 
AND updated_at < NOW() - INTERVAL '90 days';

-- Also clean up orphaned media
DELETE FROM feedback_media 
WHERE feedback_id NOT IN (SELECT id FROM feedback_items);
```

## Monitoring

### Health Check

```bash
curl http://localhost:8001/health
# {"status":"healthy"}
```

### Key Metrics to Track

1. **Open tickets count** - Should not grow unbounded
2. **Average time to resolution** - Track via `created_at` vs `resolved_at`
3. **Critical priority count** - Should be near zero
4. **Tickets by environment** - Watch production vs development ratio

### Log Analysis

```bash
# Tail logs
docker logs -f feedback-api

# Count errors
grep -c "ERROR" /var/log/feedback-api.log
```

## Deployment

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv sync
CMD ["uv", "run", "uvicorn", "ui_feedback.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Environment Variables for Production

```bash
UI_FEEDBACK_DATABASE_URL=postgresql://...
UI_FEEDBACK_CORS_ORIGINS=https://app.example.com
UI_FEEDBACK_HOST=0.0.0.0
UI_FEEDBACK_PORT=8001
```

### Scaling

The API is stateless and can be horizontally scaled behind a load balancer. The PostgreSQL database is the only stateful component.

## Troubleshooting

### "Failed to fetch" Error
- Check if backend is running: `curl http://localhost:8001/health`
- Check CORS settings in backend config
- Verify `VITE_FEEDBACK_API_URL` is correct

### Empty Tickets List
- Check browser console for API errors
- Verify `app_name` filter matches what was used when creating feedback

### Database Connection Issues
- Verify PostgreSQL is running
- Check `UI_FEEDBACK_DATABASE_URL` format
- Try memory storage for testing: `UI_FEEDBACK_USE_MEMORY_STORAGE=true`
