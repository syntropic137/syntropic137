# UI Feedback Module

A standalone, portable feedback collection system for web applications. Designed for development teams who want to capture contextual user feedback directly from their UI.

## Overview

The UI Feedback module consists of two parts:

1. **Frontend Widget** (`ui-feedback-react`) - A React component that provides an in-app feedback button with screenshot capture, element pinning, and voice notes
2. **Backend API** (`ui-feedback-api`) - A FastAPI service that stores and manages feedback tickets

## Quick Start

### 1. Start the Backend

```bash
# From the project root
just feedback-backend

# Or directly
cd lib/ui-feedback/backend/ui-feedback-api
uv run uvicorn ui_feedback.main:app --port 8001
```

The backend auto-creates database tables on first run (idempotent).

### 2. Integrate the Widget

```tsx
import { FeedbackProvider, FeedbackWidget } from '@aef/ui-feedback-react';
import '@aef/ui-feedback-react/dist/ui-feedback-react.css';

function App() {
  return (
    <FeedbackProvider
      apiUrl="http://localhost:8001/api"
      appName="my-app"
      appVersion="1.0.0"
      environment={import.meta.env.MODE}
    >
      <YourApp />
      <FeedbackWidget />
    </FeedbackProvider>
  );
}
```

## Documentation

| Guide | Description |
|-------|-------------|
| [User Guide](./user-guide.md) | How to use the feedback widget |
| [Developer Guide](./developer-guide.md) | Integration and customization |
| [Operations Guide](./operations-guide.md) | Managing feedback tickets |
| [Agent Integration](./agent-integration.md) | API for AI agents and automation |

## Features

- 🎯 **Pin to Element** - Click on any UI element to attach feedback
- 📸 **Screenshots** - Capture full page or selected areas
- 🎤 **Voice Notes** - Record audio feedback
- ⌨️ **Keyboard Shortcuts** - Quick access via hotkeys
- 🏷️ **Rich Context** - Captures URL, viewport, component name, CSS selector
- 🔄 **Environment Tracking** - Knows if feedback is from dev/staging/prod
- 💾 **Persistent Storage** - PostgreSQL or in-memory for development
- 🤖 **Agent-Friendly API** - Token-efficient endpoints for AI integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Your Application                        │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                   FeedbackProvider                       ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ ││
│  │  │FeedbackWidget│  │FeedbackModal│  │  FeedbackList   │ ││
│  │  └─────────────┘  └─────────────┘  └─────────────────┘ ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP/REST
┌─────────────────────────────────────────────────────────────┐
│                     ui-feedback-api                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  /feedback  │  │   /media    │  │      /stats         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   PostgreSQL    │
                    │   (or memory)   │
                    └─────────────────┘
```

## License

MIT
