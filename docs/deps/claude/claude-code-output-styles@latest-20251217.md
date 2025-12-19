---
# === Identity ===
package_name: claude-code-output-styles
semantic_version: latest-20251217
ecosystem: claude

# === Source ===
source_url: https://code.claude.com/docs/en/output-styles
source_type: official_docs
page_path: /docs/en/output-styles

# === Version Context ===
requested_version: latest
version_range: null
is_latest: true

# === Metadata ===
title: Output styles - Claude Code Docs
scraped_at: 2025-12-17T08:35:53.729250+00:00

# === Tooling ===
tool: firecrawl-scraper
prompt: doc-scraper/v1

# === Integrity ===
content_hash: blake3:1cb7d8ac9a5e63b1d0fa62e7834067d4210a8dea7e959e85a228b3ea1a58a2e0
---

[Skip to main content](https://code.claude.com/docs/en/output-styles#content-area)

[Claude Code Docs home page![light logo](https://mintcdn.com/claude-code/o69F7a6qoW9vboof/logo/light.svg?fit=max&auto=format&n=o69F7a6qoW9vboof&q=85&s=536eade682636e84231afce2577f9509)![dark logo](https://mintcdn.com/claude-code/o69F7a6qoW9vboof/logo/dark.svg?fit=max&auto=format&n=o69F7a6qoW9vboof&q=85&s=0766b3221061e80143e9f300733e640b)](https://code.claude.com/docs)

![US](https://d3gk2c5xim1je2.cloudfront.net/flags/US.svg)

English

Search...

Ctrl K

Search...

Navigation

Build with Claude Code

Output styles

[Getting started](https://code.claude.com/docs/en/overview) [Build with Claude Code](https://code.claude.com/docs/en/sub-agents) [Deployment](https://code.claude.com/docs/en/third-party-integrations) [Administration](https://code.claude.com/docs/en/setup) [Configuration](https://code.claude.com/docs/en/settings) [Reference](https://code.claude.com/docs/en/cli-reference) [Resources](https://code.claude.com/docs/en/legal-and-compliance)

On this page

- [Built-in output styles](https://code.claude.com/docs/en/output-styles#built-in-output-styles)
- [How output styles work](https://code.claude.com/docs/en/output-styles#how-output-styles-work)
- [Change your output style](https://code.claude.com/docs/en/output-styles#change-your-output-style)
- [Create a custom output style](https://code.claude.com/docs/en/output-styles#create-a-custom-output-style)
- [Frontmatter](https://code.claude.com/docs/en/output-styles#frontmatter)
- [Comparisons to related features](https://code.claude.com/docs/en/output-styles#comparisons-to-related-features)
- [Output Styles vs. CLAUDE.md vs. —append-system-prompt](https://code.claude.com/docs/en/output-styles#output-styles-vs-claude-md-vs-%E2%80%94append-system-prompt)
- [Output Styles vs. Agents](https://code.claude.com/docs/en/output-styles#output-styles-vs-agents)
- [Output Styles vs. Custom Slash Commands](https://code.claude.com/docs/en/output-styles#output-styles-vs-custom-slash-commands)

Output styles allow you to use Claude Code as any type of agent while keeping
its core capabilities, such as running local scripts, reading/writing files, and
tracking TODOs.

## [​](https://code.claude.com/docs/en/output-styles\#built-in-output-styles)  Built-in output styles

Claude Code’s **Default** output style is the existing system prompt, designed
to help you complete software engineering tasks efficiently.There are two additional built-in output styles focused on teaching you the
codebase and how Claude operates:

- **Explanatory**: Provides educational “Insights” in between helping you
complete software engineering tasks. Helps you understand implementation
choices and codebase patterns.
- **Learning**: Collaborative, learn-by-doing mode where Claude will not only
share “Insights” while coding, but also ask you to contribute small, strategic
pieces of code yourself. Claude Code will add `TODO(human)` markers in your
code for you to implement.

## [​](https://code.claude.com/docs/en/output-styles\#how-output-styles-work)  How output styles work

Output styles directly modify Claude Code’s system prompt.

- All output styles exclude instructions for efficient output (such as
responding concisely).
- Custom output styles exclude instructions for coding (such as verifying code
with tests), unless `keep-coding-instructions` is true.
- All output styles have their own custom instructions added to the end of the
system prompt.
- All output styles trigger reminders for Claude to adhere to the output style
instructions during the conversation.

## [​](https://code.claude.com/docs/en/output-styles\#change-your-output-style)  Change your output style

You can either:

- Run `/output-style` to access a menu and select your output style (this can
also be accessed from the `/config` menu)
- Run `/output-style [style]`, such as `/output-style explanatory`, to directly
switch to a style

These changes apply to the [local project level](https://code.claude.com/docs/en/settings) and are saved in
`.claude/settings.local.json`. You can also directly edit the `outputStyle`
field in a settings file at a different level.

## [​](https://code.claude.com/docs/en/output-styles\#create-a-custom-output-style)  Create a custom output style

Custom output styles are Markdown files with frontmatter and the text that will
be added to the system prompt:

Copy

Ask AI

```
---
name: My Custom Style
description:
  A brief description of what this style does, to be displayed to the user
---

# Custom Style Instructions

You are an interactive CLI tool that helps users with software engineering
tasks. [Your custom instructions here...]

## Specific Behaviors

[Define how the assistant should behave in this style...]
```

You can save these files at the user level (`~/.claude/output-styles`) or
project level (`.claude/output-styles`).

### [​](https://code.claude.com/docs/en/output-styles\#frontmatter)  Frontmatter

Output style files support frontmatter, useful for specifying metadata about the
command:

| Frontmatter | Purpose | Default |
| --- | --- | --- |
| `name` | Name of the output style, if not the file name | Inherits from file name |
| `description` | Description of the output style. Used only in the UI of `/output-style` | None |
| `keep-coding-instructions` | Whether to keep the parts of Claude Code’s system prompt related to coding. | false |

## [​](https://code.claude.com/docs/en/output-styles\#comparisons-to-related-features)  Comparisons to related features

### [​](https://code.claude.com/docs/en/output-styles\#output-styles-vs-claude-md-vs-%E2%80%94append-system-prompt)  Output Styles vs. CLAUDE.md vs. —append-system-prompt

Output styles completely “turn off” the parts of Claude Code’s default system
prompt specific to software engineering. Neither CLAUDE.md nor
`--append-system-prompt` edit Claude Code’s default system prompt. CLAUDE.md
adds the contents as a user message _following_ Claude Code’s default system
prompt. `--append-system-prompt` appends the content to the system prompt.

### [​](https://code.claude.com/docs/en/output-styles\#output-styles-vs-agents)  Output Styles vs. [Agents](https://code.claude.com/docs/en/sub-agents)

Output styles directly affect the main agent loop and only affect the system
prompt. Agents are invoked to handle specific tasks and can include additional
settings like the model to use, the tools they have available, and some context
about when to use the agent.

### [​](https://code.claude.com/docs/en/output-styles\#output-styles-vs-custom-slash-commands)  Output Styles vs. [Custom Slash Commands](https://code.claude.com/docs/en/slash-commands)

You can think of output styles as “stored system prompts” and custom slash
commands as “stored prompts”.

Was this page helpful?

YesNo

[Agent Skills](https://code.claude.com/docs/en/skills) [Hooks](https://code.claude.com/docs/en/hooks-guide)

Ctrl+I

Assistant

Responses are generated using AI and may contain mistakes.
