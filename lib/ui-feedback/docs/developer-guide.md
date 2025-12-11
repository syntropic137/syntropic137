# Developer Guide

How to integrate and customize the UI Feedback widget in your application.

## Installation

### Frontend (React)

```bash
# From your app directory
pnpm add @aef/ui-feedback-react

# Or link locally during development
pnpm link ../path/to/ui-feedback/packages/ui-feedback-react
```

### Backend

```bash
cd lib/ui-feedback/backend/ui-feedback-api
uv sync
```

## Basic Integration

### 1. Wrap Your App

```tsx
import { FeedbackProvider, FeedbackWidget } from '@aef/ui-feedback-react';
import '@aef/ui-feedback-react/dist/ui-feedback-react.css';

const FEEDBACK_API_URL = import.meta.env.VITE_FEEDBACK_API_URL || 'http://localhost:8001/api';

function App() {
  return (
    <FeedbackProvider
      apiUrl={FEEDBACK_API_URL}
      appName="my-app"
      appVersion="1.0.0"
    >
      <Router>
        <Routes />
      </Router>
      <FeedbackWidget />
    </FeedbackProvider>
  );
}
```

### 2. Configure Environment Variables

```bash
# .env
VITE_FEEDBACK_API_URL=http://localhost:8001/api

# Optional: for git context in feedback
VITE_GIT_COMMIT=$(git rev-parse --short HEAD)
VITE_GIT_BRANCH=$(git branch --show-current)
```

## Provider Props

```tsx
interface FeedbackProviderConfig {
  // Required
  apiUrl: string;           // Backend API URL
  appName: string;          // Your app's name

  // Optional - App info
  appVersion?: string;      // Semantic version
  
  // Optional - Environment context
  environment?: string;     // 'development' | 'staging' | 'production'
  gitCommit?: string;       // Git commit hash
  gitBranch?: string;       // Git branch name
  hostname?: string;        // Server hostname
  
  // Optional - Widget behavior
  keyboardShortcut?: string;  // Default: 'Ctrl+Shift+F'
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  
  // Optional - Theming
  primaryColor?: string;    // Brand color
  accentColor?: string;     // Secondary color
}
```

### Full Example with Environment Context

```tsx
<FeedbackProvider
  apiUrl={import.meta.env.VITE_FEEDBACK_API_URL}
  appName="aef-dashboard"
  appVersion="0.1.0"
  environment={import.meta.env.MODE}
  gitCommit={import.meta.env.VITE_GIT_COMMIT}
  gitBranch={import.meta.env.VITE_GIT_BRANCH}
  hostname={window.location.hostname}
  keyboardShortcut="Ctrl+Shift+F"
  position="bottom-right"
>
```

## Backend Configuration

### Environment Variables

```bash
# Database (PostgreSQL)
UI_FEEDBACK_DATABASE_URL=postgresql://user:pass@localhost:5432/feedback

# Or use in-memory storage for development
UI_FEEDBACK_USE_MEMORY_STORAGE=true

# CORS (comma-separated origins)
UI_FEEDBACK_CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Server
UI_FEEDBACK_HOST=0.0.0.0
UI_FEEDBACK_PORT=8001
```

### Running the Backend

```bash
# Development with auto-reload
uv run uvicorn ui_feedback.main:app --reload --port 8001

# Production
uv run uvicorn ui_feedback.main:app --host 0.0.0.0 --port 8001
```

### Database Migrations

Migrations run automatically on startup (idempotent). For manual control:

```bash
# Using psql directly
psql $UI_FEEDBACK_DATABASE_URL -f src/ui_feedback/migrations/001_feedback_tables.sql
```

## Customization

### Theming

The widget uses CSS variables for theming:

```css
.ui-feedback-theme {
  --feedback-primary: #6366f1;
  --feedback-primary-hover: #4f46e5;
  --feedback-success: #22c55e;
  --feedback-warning: #f59e0b;
  --feedback-error: #ef4444;
  --feedback-bg: #ffffff;
  --feedback-surface: #f8fafc;
  --feedback-border: #e2e8f0;
  --feedback-text-primary: #0f172a;
  --feedback-text-secondary: #64748b;
}
```

Override in your CSS:

```css
.ui-feedback-theme {
  --feedback-primary: #your-brand-color;
}
```

### Programmatic Control

```tsx
import { useFeedback } from '@aef/ui-feedback-react';

function MyComponent() {
  const { openFeedback, openQuickFeedback } = useFeedback();
  
  return (
    <button onClick={() => openQuickFeedback()}>
      Report Issue
    </button>
  );
}
```

## TypeScript Support

Type declarations are included. Add to your `tsconfig.json` if using local linking:

```json
{
  "compilerOptions": {
    "paths": {
      "@aef/ui-feedback-react": ["./lib/ui-feedback/packages/ui-feedback-react/src"]
    }
  }
}
```

## Building the Package

```bash
cd lib/ui-feedback/packages/ui-feedback-react
pnpm build
```

Outputs:
- `dist/index.js` - ES module
- `dist/index.cjs` - CommonJS
- `dist/ui-feedback-react.css` - Styles
- `dist/*.d.ts` - Type declarations

## Portability

The UI Feedback module is designed to be portable to other projects:

1. Copy the `lib/ui-feedback` directory
2. Install dependencies in both `packages/ui-feedback-react` and `backend/ui-feedback-api`
3. Configure environment variables
4. Import and use

No dependencies on the parent monorepo are required.
