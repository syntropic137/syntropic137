# Firecrawl Scraper Tool

Web scraping tool using the [Firecrawl](https://firecrawl.dev) API to extract web content as clean markdown.

## Features

- 🔥 Scrapes web pages via Firecrawl API
- 📝 Outputs clean markdown with YAML frontmatter
- 🏷️ Supports version tagging for documentation
- 📊 Integrates with `agentic_logging` for session tracking
- ⚙️ Validates API key via `agentic_settings`

## Requirements

- Python 3.11+
- Firecrawl API key (set `FIRECRAWL_API_KEY` environment variable)

## Installation

```bash
# Install with uv
uv pip install -e .

# Or run directly
uv run firecrawl_scraper.py scrape <url> <output_path>
```

## Usage

### Basic Scrape

```bash
uv run firecrawl_scraper.py scrape https://docs.pydantic.dev/latest/ docs/pydantic.md
```

### With Version Tag

```bash
uv run firecrawl_scraper.py scrape \
  https://docs.pydantic.dev/2.5/ \
  docs/deps/pydantic-2.5.0.md \
  --version 2.5.0
```

### With Custom Title

```bash
uv run firecrawl_scraper.py scrape \
  https://example.com/api \
  docs/api-reference.md \
  --title "API Reference Guide"
```

### With Session Tracking

```bash
uv run firecrawl_scraper.py scrape \
  https://example.com \
  output.md \
  --session-id "task-123-abc"
```

## Output Format

The scraped content is saved as markdown with YAML frontmatter:

```markdown
---
source_url: https://docs.pydantic.dev/latest/
title: Pydantic Documentation
scraped_at: 2025-11-29T10:30:00Z
version: 2.5.0
tool: firecrawl-scraper
---

# Page Content

The actual page content in markdown format...
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FIRECRAWL_API_KEY` | Yes | Your Firecrawl API key |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## API

### CLI Commands

#### `scrape`

Scrape a URL and save as markdown.

```
firecrawl_scraper.py scrape URL OUTPUT_PATH [OPTIONS]

Arguments:
  URL          URL to scrape
  OUTPUT_PATH  Output file path

Options:
  --title TEXT       Override document title
  --version TEXT     Version tag for frontmatter
  --session-id TEXT  Session ID for logging
  --formats TEXT     Comma-separated formats (default: markdown)
```

## Error Handling

- Missing `FIRECRAWL_API_KEY` raises `MissingProviderError` with setup instructions
- Invalid URLs are validated before making API calls
- Network errors are caught and logged with context

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest

# Type check
uv run mypy firecrawl_scraper.py

# Lint
uv run ruff check .
```

## License

MIT

