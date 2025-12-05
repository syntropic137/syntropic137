# ADR-016: UI Feedback Module

## Status
**Proposed** - December 2025

## Context

During development and QA review of applications in this monorepo, we need a way to capture feedback directly from the UI. Currently, feedback is communicated through external tools (Slack, email, GitHub issues) which loses important context like:
- Exact URL and route where the issue occurred
- Screen dimensions and coordinates
- Visual context (screenshots)
- Component information

Vercel's Toolbar/Comments feature demonstrates an effective pattern for in-context feedback, but we need a self-hosted, reusable solution that:
1. Works across multiple apps in the monorepo
2. Stores feedback in our existing PostgreSQL database
3. Provides API access for AI agents (Cursor) to query and manage feedback
4. Supports multiple input methods (text, voice, screenshots)

## Decision

Build a self-contained `ui-feedback` module with two packages:

### 1. Frontend: `ui-feedback-react`
A React component library that can be integrated into any React application.

**Key Components:**
- `FeedbackProvider` - Context provider, configures API endpoint
- `FeedbackWidget` - Floating button + modal
- `AreaSelector` - Overlay for region screenshot capture
- `VoiceRecorder` - Audio recording component

**Features:**
- Click anywhere to pin feedback location
- Capture: text comments, voice notes, screenshots (drag/drop, paste, area select, full page)
- Auto-detect: URL, viewport size, coordinates, CSS selector, XPath, React component name
- Keyboard shortcut to toggle (configurable)

### 2. Backend: `ui-feedback-api`
A Python FastAPI service that can run standalone or be mounted into existing FastAPI apps.

**Features:**
- CRUD operations for feedback items
- Media storage (PostgreSQL BYTEA for dev, S3-ready interface)
- Status management (ticket workflow)
- Query filtering for AI agent consumption

### Data Model

```sql
CREATE TABLE feedback_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Location context
    url TEXT NOT NULL,
    route TEXT,
    viewport_width INT,
    viewport_height INT,
    click_x INT,
    click_y INT,
    css_selector TEXT,
    xpath TEXT,
    component_name TEXT,

    -- Feedback content
    feedback_type VARCHAR(20) DEFAULT 'bug',  -- bug, feature, ui_ux, performance, question, other
    comment TEXT,

    -- Ticket workflow
    status VARCHAR(20) DEFAULT 'open',  -- open, in_progress, resolved, closed, wont_fix
    priority VARCHAR(10) DEFAULT 'medium',  -- low, medium, high, critical
    assigned_to TEXT,
    resolution_notes TEXT,

    -- Metadata
    app_name TEXT NOT NULL,
    app_version TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE feedback_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id UUID NOT NULL REFERENCES feedback_items(id) ON DELETE CASCADE,
    media_type VARCHAR(20) NOT NULL,  -- screenshot, voice_note
    mime_type VARCHAR(50) NOT NULL,
    file_name TEXT,
    file_size INT,
    data BYTEA,  -- For dev/local storage
    external_url TEXT,  -- For S3/Supabase (future)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feedback_status ON feedback_items(status);
CREATE INDEX idx_feedback_app ON feedback_items(app_name);
CREATE INDEX idx_feedback_type ON feedback_items(feedback_type);
CREATE INDEX idx_feedback_created ON feedback_items(created_at DESC);
CREATE INDEX idx_feedback_media_feedback ON feedback_media(feedback_id);
```

### API Endpoints

```
# Feedback Items
GET    /api/feedback                    # List (filterable: status, type, app, priority)
GET    /api/feedback/:id                # Get single item with media
POST   /api/feedback                    # Create new feedback
PATCH  /api/feedback/:id                # Update status/priority/assignment/notes
DELETE /api/feedback/:id                # Delete feedback

# Media (separate for large files)
POST   /api/feedback/:id/media          # Upload media (screenshot/voice)
GET    /api/feedback/:id/media/:mediaId # Get media file
DELETE /api/feedback/:id/media/:mediaId # Delete media

# Stats
GET    /api/feedback/stats              # Aggregate stats for dashboard
```

### Module Structure

```
lib/ui-feedback/
├── README.md
├── packages/
│   └── ui-feedback-react/
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       └── src/
│           ├── index.ts                 # Public exports
│           ├── FeedbackProvider.tsx
│           ├── FeedbackWidget.tsx
│           ├── components/
│           │   ├── FeedbackModal.tsx
│           │   ├── FeedbackButton.tsx
│           │   ├── AreaSelector.tsx
│           │   ├── VoiceRecorder.tsx
│           │   ├── ScreenshotUploader.tsx
│           │   └── LocationPin.tsx
│           ├── hooks/
│           │   ├── useFeedbackApi.ts
│           │   ├── useScreenCapture.ts
│           │   ├── useVoiceRecorder.ts
│           │   └── useElementInfo.ts
│           ├── utils/
│           │   ├── getReactComponent.ts
│           │   ├── getElementPath.ts
│           │   └── captureArea.ts
│           └── types/
│               └── index.ts
│
└── backend/
    └── ui-feedback-api/
        ├── pyproject.toml
        ├── src/
        │   └── ui_feedback/
        │       ├── __init__.py
        │       ├── main.py              # Standalone runner
        │       ├── router.py            # Mountable FastAPI router
        │       ├── api/
        │       │   ├── __init__.py
        │       │   ├── feedback.py
        │       │   ├── media.py
        │       │   └── stats.py
        │       ├── models/
        │       │   ├── __init__.py
        │       │   ├── feedback.py
        │       │   └── media.py
        │       ├── storage/
        │       │   ├── __init__.py
        │       │   ├── protocol.py      # Abstract interface
        │       │   ├── postgres.py
        │       │   └── s3.py            # Future
        │       └── migrations/
        │           └── 001_feedback_tables.sql
        └── tests/
            ├── __init__.py
            ├── test_api.py
            └── test_storage.py
```

## Consequences

### Positive
1. **Reusable** - Can integrate into any React app in monorepo
2. **Context-rich** - Captures all relevant debugging context automatically
3. **AI-friendly** - REST API enables Cursor/agents to manage feedback as tickets
4. **Self-contained** - No external dependencies for core functionality
5. **Extensible** - Storage abstraction allows S3 migration later

### Negative
1. **Initial development time** - ~2-3 days for MVP
2. **Bundle size** - html2canvas adds ~40KB gzipped
3. **PostgreSQL dependency** - Requires database for backend

### Risks
1. **html2canvas limitations** - May not capture all CSS perfectly
2. **Voice recording browser support** - MediaRecorder varies by browser
3. **React fiber access** - May break in future React versions

## Future Enhancements
- [ ] S3/Supabase media storage
- [ ] Authentication integration
- [ ] Real-time updates (WebSocket)
- [ ] Slack/Discord notifications
- [ ] AI-powered categorization
- [ ] Screenshot annotation tools

## References
- [Vercel Toolbar](https://vercel.com/docs/vercel-toolbar)
- [html2canvas](https://html2canvas.hertzen.com/)
- [MediaRecorder API](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
