# UI Feedback API

FastAPI backend for the UI Feedback module.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server
UI_FEEDBACK_DATABASE_URL=postgresql://... uv run uvicorn ui_feedback.main:app --reload --port 8001
```

## API Endpoints

- `GET /api/feedback` - List feedback items
- `POST /api/feedback` - Create feedback
- `GET /api/feedback/:id` - Get single feedback
- `PATCH /api/feedback/:id` - Update feedback status
- `DELETE /api/feedback/:id` - Delete feedback
- `GET /api/feedback/stats` - Get statistics

See `/docs` for full OpenAPI documentation.
