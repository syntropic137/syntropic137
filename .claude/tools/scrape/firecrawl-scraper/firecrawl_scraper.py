#!/usr/bin/env python3
"""
Firecrawl Scraper Tool

Scrape web pages using Firecrawl API and save as markdown with metadata frontmatter.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, Field, HttpUrl
from rich.console import Console
from rich.panel import Panel

# Initialize console for rich output
console = Console()
err_console = Console(stderr=True)

# Initialize Typer app
app = typer.Typer(
    name="firecrawl-scraper",
    help="Scrape web pages using Firecrawl API and save as markdown.",
    no_args_is_help=True,
)

# Logger
logger = logging.getLogger(__name__)


class ScrapeResult(BaseModel):
    """Result of a successful scrape operation."""

    path: str = Field(description="Path to the saved file")
    bytes: int = Field(description="Size of the content in bytes")
    source_url: str = Field(description="Original URL that was scraped")
    title: str = Field(description="Document title")
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScrapeMetadata(BaseModel):
    """Metadata for the scraped document frontmatter."""

    source_url: HttpUrl
    title: str
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: str | None = None
    tool: str = "firecrawl-scraper"
    session_id: str | None = None


def get_firecrawl_api_key() -> str:
    """
    Get Firecrawl API key from agentic_settings or environment.

    Returns:
        The Firecrawl API key.

    Raises:
        typer.Exit: If API key is not configured.
    """
    import os

    # First try agentic_settings
    try:
        from agentic_settings import get_settings

        settings = get_settings()
        if settings.firecrawl_api_key:
            return settings.firecrawl_api_key.get_secret_value()
    except ImportError:
        logger.debug("agentic_settings not available, falling back to environment")
    except Exception as e:
        logger.debug(f"Error loading agentic_settings: {e}")

    # Fall back to environment variable
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        err_console.print(
            Panel(
                "[red]Missing Firecrawl API Key[/red]\n\n"
                "Set the FIRECRAWL_API_KEY environment variable:\n"
                "  export FIRECRAWL_API_KEY=fc-your-key\n\n"
                "Get your API key at: https://firecrawl.dev",
                title="Configuration Error",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    return api_key


def generate_frontmatter(metadata: ScrapeMetadata) -> str:
    """Generate YAML frontmatter from metadata."""
    lines = [
        "---",
        f"source_url: {metadata.source_url}",
        f"title: {metadata.title}",
        f"scraped_at: {metadata.scraped_at.isoformat()}",
    ]

    if metadata.version:
        lines.append(f"version: {metadata.version}")

    lines.append(f"tool: {metadata.tool}")

    if metadata.session_id:
        lines.append(f"session_id: {metadata.session_id}")

    lines.append("---")
    return "\n".join(lines)


def scrape_url(
    url: str,
    api_key: str,
    formats: list[str] | None = None,
) -> tuple[str, str]:
    """
    Scrape a URL using Firecrawl API.

    Args:
        url: URL to scrape
        api_key: Firecrawl API key
        formats: Output formats to request

    Returns:
        Tuple of (content, title)

    Raises:
        Exception: If scraping fails
    """
    from firecrawl import FirecrawlApp

    if formats is None:
        formats = ["markdown"]

    client = FirecrawlApp(api_key=api_key)

    logger.info(f"Scraping URL: {url}")
    result = client.scrape(url, formats=formats)

    # Extract content (SDK v2 returns Pydantic Document model)
    content = result.markdown or ""
    if not content and hasattr(result, "html"):
        content = result.html or ""

    # Extract title from metadata or content
    metadata = result.metadata_dict if hasattr(result, "metadata_dict") else {}
    title = metadata.get("title", "") if metadata else ""
    if not title:
        # Try to extract from first heading
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        if not title:
            title = "Untitled Document"

    return content, title


def save_markdown(
    content: str,
    output_path: Path,
    metadata: ScrapeMetadata,
) -> ScrapeResult:
    """
    Save scraped content as markdown with frontmatter.

    Args:
        content: Markdown content
        output_path: Path to save file
        metadata: Document metadata

    Returns:
        ScrapeResult with file details
    """
    # Generate frontmatter
    frontmatter = generate_frontmatter(metadata)

    # Combine frontmatter and content
    full_content = f"{frontmatter}\n\n{content}"

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    output_path.write_text(full_content, encoding="utf-8")

    logger.info(f"Saved to: {output_path}")

    return ScrapeResult(
        path=str(output_path),
        bytes=len(full_content.encode("utf-8")),
        source_url=str(metadata.source_url),
        title=metadata.title,
        scraped_at=metadata.scraped_at,
    )


@app.command()
def scrape(
    url: Annotated[str, typer.Argument(help="URL to scrape")],
    output_path: Annotated[str, typer.Argument(help="Output file path")],
    title: Annotated[
        str | None,
        typer.Option("--title", "-t", help="Override document title"),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Version tag for frontmatter"),
    ] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", "-s", help="Session ID for logging"),
    ] = None,
    formats: Annotated[
        str | None,
        typer.Option("--formats", "-f", help="Comma-separated output formats"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable verbose output"),
    ] = False,
) -> None:
    """
    Scrape a URL and save as markdown with frontmatter.

    Example:
        firecrawl_scraper.py scrape https://docs.pydantic.dev/ docs/pydantic.md --version 2.5.0
    """
    # Configure logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Log session if provided
    if session_id:
        logger.info(f"Session: {session_id}")

    try:
        # Get API key
        api_key = get_firecrawl_api_key()

        # Parse formats
        format_list = formats.split(",") if formats else ["markdown"]

        # Scrape URL
        content, detected_title = scrape_url(url, api_key, format_list)

        # Use provided title or detected title
        final_title = title or detected_title

        # Create metadata
        metadata = ScrapeMetadata(
            source_url=url,  # type: ignore[arg-type]
            title=final_title,
            version=version,
            session_id=session_id,
        )

        # Save file
        result = save_markdown(content, Path(output_path), metadata)

        # Output result
        console.print(
            Panel(
                f"[green]✓ Scraped successfully[/green]\n\n"
                f"URL: {result.source_url}\n"
                f"Title: {result.title}\n"
                f"Saved to: {result.path}\n"
                f"Size: {result.bytes:,} bytes",
                title="Scrape Complete",
                border_style="green",
            )
        )

    except Exception as e:
        logger.exception("Scrape failed")
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Show version information."""
    console.print("firecrawl-scraper v0.1.0")


if __name__ == "__main__":
    app()

