# User Guide

How to use the UI Feedback widget to report issues and suggestions.

## Opening the Feedback Widget

### Using the Button
Click the feedback button (💬) in the bottom-right corner of the screen.

### Using Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+F` | Open feedback menu |
| `Ctrl+Shift+Q` | Quick note (no element pinning) |
| `Ctrl+Shift+T` | View tickets |
| `Escape` | Close any open modal |

## Feedback Options

### 1. Quick Note
For general feedback not tied to a specific element.

1. Press `Ctrl+Shift+Q` or click "Quick Note" from the menu
2. Select feedback type (Bug, Feature, UI/UX, etc.)
3. Set priority if needed
4. Type your feedback
5. Click "Submit Feedback"

### 2. Pin to Element
Attach feedback to a specific UI element.

1. Press `Ctrl+Shift+F` or click "Pin to Element"
2. Hover over elements - they'll highlight as you move
3. Click the element you want to report about
4. The feedback modal opens with element context captured
5. Describe the issue and submit

**What gets captured:**
- React component name (e.g., `<MetricCard>`)
- CSS selector path
- XPath
- Click coordinates
- Viewport size

### 3. View Tickets
See all feedback you've submitted.

1. Press `Ctrl+Shift+T` or click "View Tickets"
2. Filter by status: Open, In Progress, Resolved, Closed
3. Click a ticket to see details
4. Change status using the dropdown

## Feedback Types

| Type | Emoji | Use For |
|------|-------|---------|
| Bug | 🐛 | Something broken or not working |
| Feature | ✨ | New functionality request |
| UI/UX | 🎨 | Design or usability improvements |
| Performance | ⚡ | Slow or laggy behavior |
| Question | ❓ | Need clarification |
| Other | 📝 | Anything else |

## Priority Levels

| Priority | When to Use |
|----------|-------------|
| Low | Nice-to-have, not urgent |
| Medium | Should be addressed soon (default) |
| High | Important issue affecting work |
| Critical | Blocking issue, needs immediate attention |

## Attaching Screenshots

### Capture Area
1. Click the crop icon in the feedback modal
2. Draw a rectangle around the area to capture
3. The screenshot is attached automatically

### Full Page
Click the full-page icon to capture the entire visible page.

### Upload Image
Click the upload icon to attach an existing image file.

### Paste Image
Copy an image to your clipboard and paste (`Ctrl+V`) directly into the feedback modal.

## Recording Voice Notes

1. Click the microphone icon 🎤
2. Allow microphone access if prompted
3. Speak your feedback
4. Click stop when done
5. The audio is attached to your feedback

## Tips for Good Feedback

1. **Be specific** - "Button doesn't work" → "Submit button on /settings page shows error when clicked"
2. **Use Pin to Element** - It captures technical context automatically
3. **Include steps to reproduce** - What did you do before the issue occurred?
4. **Set appropriate priority** - Reserve Critical for actual blockers
5. **Attach screenshots** - A picture is worth a thousand words

## Viewing Your Feedback

All feedback is stored and can be viewed in the tickets panel. Developers and agents can see your feedback and work on resolving issues.
