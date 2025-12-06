# UI Feedback Module

A self-contained, reusable feedback widget for React applications with a Python FastAPI backend.

## Features

- **Click-to-Comment**: Click anywhere on the page to pin feedback to a specific location
- **Rich Context Capture**: Automatically captures URL, viewport, coordinates, CSS selector, XPath, React component name
- **Multiple Input Methods**:
  - Text comments
  - Voice notes (browser recording)
  - Screenshots (area select, full page, drag/drop, paste)
- **Ticket Workflow**: Status management (open → in_progress → resolved → closed)
- **AI-Friendly API**: REST endpoints for agents to query and manage feedback
- **Customizable Styling**: Pass custom themes/classNames to match your app's design

## Packages

| Package | Description |
|---------|-------------|
| `ui-feedback-react` | React component library |
| `ui-feedback-api` | Python FastAPI backend |

## Quick Start

### 1. Install the React package

```bash
# From your React app directory
npm install @lib/ui-feedback-react
# or
pnpm add @lib/ui-feedback-react
```

### 2. Add the provider and widget

```tsx
import { FeedbackProvider, FeedbackWidget } from '@lib/ui-feedback-react';

function App() {
  return (
    <FeedbackProvider
      apiUrl="http://localhost:8001/api/feedback"
      appName="my-app"
      appVersion="1.0.0"
    >
      <YourApp />
      <FeedbackWidget />
    </FeedbackProvider>
  );
}
```

### 3. Run the backend

```bash
# From lib/ui-feedback/backend/ui-feedback-api
uv run uvicorn ui_feedback.main:app --reload --port 8001
```

### 4. Run the database migration

```bash
psql $DATABASE_URL -f migrations/001_feedback_tables.sql
```

## Configuration

### Frontend (FeedbackProvider props)

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `apiUrl` | `string` | Yes | Base URL for the feedback API |
| `appName` | `string` | Yes | Name of your application |
| `appVersion` | `string` | No | Version of your application |
| `keyboardShortcut` | `string` | No | Shortcut to toggle feedback mode (default: `Ctrl+Shift+F`) |
| `theme` | `Theme` | No | Custom theme colors |
| `classNames` | `ClassNames` | No | Custom class names for components |
| `position` | `'bottom-right' \| 'bottom-left' \| 'top-right' \| 'top-left'` | No | Widget position (default: `'bottom-right'`) |

### Backend (Environment Variables)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UI_FEEDBACK_DATABASE_URL` | Yes | - | PostgreSQL connection string |
| `UI_FEEDBACK_MAX_FILE_SIZE` | No | `10485760` | Max upload size in bytes (10MB) |
| `UI_FEEDBACK_CORS_ORIGINS` | No | `*` | Allowed CORS origins |

## API Endpoints

### Feedback Items

```
GET    /api/feedback                    # List feedback (filterable)
GET    /api/feedback/:id                # Get single feedback with media
POST   /api/feedback                    # Create new feedback
PATCH  /api/feedback/:id                # Update feedback
DELETE /api/feedback/:id                # Delete feedback
```

### Media

```
POST   /api/feedback/:id/media          # Upload media
GET    /api/feedback/:id/media/:mediaId # Download media
DELETE /api/feedback/:id/media/:mediaId # Delete media
```

### Stats

```
GET    /api/feedback/stats              # Aggregate statistics
```

## Custom Styling

### Using Theme

```tsx
<FeedbackProvider
  apiUrl="..."
  appName="..."
  theme={{
    primary: '#6366f1',
    background: '#1e1e2e',
    surface: '#2a2a3e',
    border: '#3a3a4e',
    text: '#ffffff',
    textSecondary: '#a0a0b0',
  }}
>
```

### Using ClassNames

```tsx
<FeedbackProvider
  apiUrl="..."
  appName="..."
  classNames={{
    button: 'my-custom-button',
    modal: 'my-custom-modal',
    overlay: 'my-custom-overlay',
  }}
>
```

## Architecture

See [ADR-016: UI Feedback Module](../../docs/adrs/ADR-016-ui-feedback-module.md) for detailed architecture decisions.

## License

MIT
