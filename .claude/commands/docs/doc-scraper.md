---
description: Scrape developer documentation with package@version format and structured output
argument-hint: <package>@<version> <url> [--ecosystem <eco>] [--range "<range>"]
model: sonnet
allowed-tools: Read, Write, Bash
---

# Documentation Scraper

Scrape developer documentation with explicit semantic versioning, producing structured markdown with rich frontmatter for agent context.

## Purpose

Fetch documentation from a URL and save it with a `<package>@<semver>` naming convention. This ensures documentation context is always tied to an explicit version, enabling reproducible agent workflows and precise dependency tracking.

## Variables

PACKAGE_SPEC: $1  # Format: <package-name>@<version> (e.g., pydantic@2.5.0, fastapi@latest)
SOURCE_URL: $2    # URL to scrape (e.g., https://docs.pydantic.dev/2.5/concepts/models/)
ECOSYSTEM: $3     # Optional: python, rust, javascript, go, ruby (auto-detected if omitted)
VERSION_RANGE: $4 # Optional: Compatibility range (e.g., ">=2.5.0,<3.0.0")
OUTPUT_BASE: docs/deps  # Base directory for scraped docs
FIRECRAWL_TOOL: primitives/v1/tools/scrape/firecrawl-scraper/firecrawl_scraper.py

## Instructions

- Parse PACKAGE_SPEC to extract `package_name` and `requested_version`
- If version is `latest`, attempt to resolve to explicit semver from URL or page content
- Validate that extracted version follows semver pattern (X.Y.Z with optional pre-release/build)
- Detect ecosystem from URL domain if not explicitly provided
- Generate output path as `{OUTPUT_BASE}/{ecosystem}/{package_name}@{resolved_version}.md`
- Always save with explicit version - never `@latest` in the output filename
- Include full frontmatter with identity, source, version context, and content hash

## Workflow

1. **Parse Package Specification**
   - Split PACKAGE_SPEC on `@` to get `package_name` and `requested_version`
   - If no `@` present: stop with error "Invalid format. Use: package@version"
   - If `requested_version` is empty: stop with error "Version required after @"

2. **Detect Ecosystem**
   - If ECOSYSTEM provided: use it directly
   - Else, detect from SOURCE_URL:
     - `docs.python.org`, `pypi.org`, `readthedocs.io`, `*.python*` → `python`
     - `docs.rs`, `crates.io`, `doc.rust-lang.org` → `rust`
     - `npmjs.com`, `nodejs.org`, `deno.land` → `javascript`
     - `pkg.go.dev`, `golang.org`, `go.dev` → `go`
     - `rubydoc.info`, `rubygems.org`, `ruby-doc.org` → `ruby`
     - `docs.swift.org`, `swiftpackageindex.com` → `swift`
     - Otherwise → `unknown`

3. **Resolve Version**
   - If `requested_version` matches semver pattern (`\d+\.\d+\.\d+.*`): 
     - Use it as `resolved_version`
   - If `requested_version` is `latest`:
     - Try to extract from URL path (e.g., `/2.5/`, `/v1.0.193/`, `/0.104.1/`)
     - If found: use as `resolved_version`, set `is_latest: true`
     - If not found: warn user, use `latest-YYYYMMDD` format as fallback

4. **Generate Output Path**
   - Construct: `{OUTPUT_BASE}/{ecosystem}/{package_name}@{resolved_version}.md`
   - Example: `docs/deps/python/pydantic@2.5.0.md`

5. **Scrape Documentation**
   - Run firecrawl-scraper tool:
     ```bash
     cd {repo_root}
     uv run {FIRECRAWL_TOOL} scrape "{SOURCE_URL}" "{temp_output}" --version "{resolved_version}"
     ```
   - If scrape fails: stop with error message from tool

6. **Extract Page Metadata**
   - Read scraped content
   - Extract `title` from first `# Heading` or frontmatter
   - Extract `page_path` from URL (path after domain)
   - Determine `source_type`:
     - URL contains `/api/` or `/reference/` → `api_ref`
     - URL contains `/tutorial/` or `/guide/` → `tutorial`
     - URL contains `github.com` → `github`
     - Otherwise → `official_docs`

7. **Compute Content Hash**
   - Calculate BLAKE3 hash of the markdown content (excluding frontmatter)
   - Format: `blake3:{hash}`

8. **Generate Enhanced Frontmatter**
   - Build frontmatter with all fields from Output Format section
   - Prepend to scraped content

9. **Write Output File**
   - Ensure output directory exists
   - Write file to generated output path
   - Report success with file details

## Output Format

The scraped documentation is saved with this enhanced frontmatter structure:

```yaml
---
# === Identity ===
package_name: {package_name}
semantic_version: {resolved_version}
ecosystem: {ecosystem}

# === Source ===
source_url: {SOURCE_URL}
source_type: {detected_source_type}
page_path: {extracted_page_path}

# === Version Context ===
requested_version: {requested_version}
version_range: {VERSION_RANGE or null}
is_latest: {true if resolved from latest, false otherwise}

# === Metadata ===
title: {extracted_title}
scraped_at: {ISO 8601 timestamp}

# === Tooling ===
tool: firecrawl-scraper
prompt: doc-scraper/v1
session_id: {session_id if provided}

# === Integrity ===
content_hash: blake3:{hash}
---

{scraped markdown content}
```

## Examples

### Example 1: Scrape with explicit version

```
/doc-scraper pydantic@2.5.0 https://docs.pydantic.dev/2.5/concepts/models/
```

**Output:** `docs/deps/python/pydantic@2.5.0.md`

```yaml
---
package_name: pydantic
semantic_version: 2.5.0
ecosystem: python
source_url: https://docs.pydantic.dev/2.5/concepts/models/
source_type: official_docs
page_path: /2.5/concepts/models/
requested_version: 2.5.0
version_range: null
is_latest: false
title: "Models - Pydantic"
scraped_at: 2025-11-29T14:30:00Z
tool: firecrawl-scraper
prompt: doc-scraper/v1
content_hash: blake3:a1b2c3d4e5f6...
---
```

### Example 2: Scrape latest (resolved from URL)

```
/doc-scraper fastapi@latest https://fastapi.tiangolo.com/0.104.1/tutorial/first-steps/
```

**Output:** `docs/deps/python/fastapi@0.104.1.md`

```yaml
---
package_name: fastapi
semantic_version: 0.104.1
ecosystem: python
source_url: https://fastapi.tiangolo.com/0.104.1/tutorial/first-steps/
requested_version: latest
is_latest: true
# ...
---
```

### Example 3: Explicit ecosystem and version range

```
/doc-scraper axios@1.6.2 https://axios-http.com/docs/intro --ecosystem javascript --range ">=1.0.0,<2.0.0"
```

**Output:** `docs/deps/javascript/axios@1.6.2.md`

```yaml
---
package_name: axios
semantic_version: 1.6.2
ecosystem: javascript
version_range: ">=1.0.0,<2.0.0"
# ...
---
```

### Example 4: Rust crate documentation

```
/doc-scraper serde@1.0.193 https://docs.rs/serde/1.0.193/serde/
```

**Output:** `docs/deps/rust/serde@1.0.193.md`

```yaml
---
package_name: serde
semantic_version: 1.0.193
ecosystem: rust
source_url: https://docs.rs/serde/1.0.193/serde/
source_type: api_ref
# ...
---
```

## Report

## Documentation Scraped

**Package:** {package_name}@{resolved_version}
**Ecosystem:** {ecosystem}
**Source:** {SOURCE_URL}

**Output:** `{output_path}`
**Size:** {file_size} bytes
**Content Hash:** {content_hash}

| Field | Value |
|-------|-------|
| Requested Version | {requested_version} |
| Resolved Version | {resolved_version} |
| Version Range | {VERSION_RANGE or "—"} |
| Source Type | {source_type} |
| Scraped At | {timestamp} |

