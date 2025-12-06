---
description: Generate agentic prompts at any level with proper structure
argument-hint: <level 1-7> <high-level description of what the prompt should do>
model: sonnet
allowed-tools: Read, Write
---

# Prompt Generator

Generate a new agentic prompt at the specified level with all appropriate sections.

## Purpose

Create well-structured, reusable agentic prompts that communicate clearly to three audiences: you, your team, and your agents.

## Variables

LEVEL: $1  # 1-7, defaults to 2 (workflow prompt)
DESCRIPTION: $2  # High-level description of what the prompt should do
OUTPUT_DIR: primitives/v1/prompts/commands
PROMPT_ID: # Derived from description (kebab-case)
CATEGORY: # Inferred from description

## Instructions

1. Parse the level and description from arguments
2. Determine appropriate category from description
3. Generate prompt ID in kebab-case from description
4. Select the template for the specified level
5. Fill in the template with appropriate content
6. Create both the .yaml metadata and .prompt.v1.md content files

## The 7 Levels of Agentic Prompts

| Level | Name | Key Capability | Sections |
|-------|------|----------------|----------|
| 1 | High-Level | Simple reusable task | Title, Purpose, Task |
| 2 | Workflow | Sequential steps | + Variables, Workflow, Report |
| 3 | Control Flow | Conditionals, loops | + If/else, loops, early returns |
| 4 | Delegation | Sub-agent orchestration | + Agent spawning, parallel work |
| 5 | Higher-Order | Prompts accepting prompts | + Dynamic plan/prompt input |
| 6 | Template Meta | Prompt generation | + Template section, format spec |
| 7 | Self-Improving | Dynamic expertise | + Expertise section, self-update |

## Composable Sections Reference

### S-Tier (Most Useful)
- **Workflow** - Step-by-step play for your agent
- **Delegation** - Spawn and coordinate sub-agents

### A-Tier (Very Useful)
- **Variables** - Static and dynamic inputs
- **Examples** - Show expected behavior/output
- **Template** - Structured output format
- **Purpose** - Direct statement of intent

### B-Tier (Useful)
- **Report** - Output format specification
- **Instructions** - Auxiliary guidance for workflow
- **Task** - Simple high-level description

### C-Tier (Situational)
- **Metadata** - Model, tools, description
- **Codebase Structure** - Context map of files
- **Relevant Files** - Quick reference to key files

## Workflow

1. **Parse Input**
   - Extract level (default: 2)
   - Extract description
   - Generate kebab-case ID
   - Infer category

2. **Select Template**
   - Choose template based on level
   - Levels stack: Level 3 includes Level 2 sections, etc.

3. **Generate Metadata File**
   - Create `{id}.yaml` with:
     - id, kind, category, domain, summary
     - tags, defaults, tools, versions

4. **Generate Prompt File**
   - Create `{id}.prompt.v1.md` using level template
   - Fill sections with appropriate content
   - Use direct tone of voice (talking to agent)

5. **Output**
   - Write files to OUTPUT_DIR/{category}/{id}/

## Templates

### Level 1: High-Level Prompt

```markdown
---
description: {description}
---

# {Title}

## Purpose

{One sentence: what this prompt does, talking to agent}

## Task

{High-level description of what to do}
```

### Level 2: Workflow Prompt

```markdown
---
description: {description}
argument-hint: {argument hint}
model: sonnet
allowed-tools: {tools}
---

# {Title}

## Purpose

{Direct statement of what this prompt accomplishes}

## Variables

{VARIABLE_NAME}: $ARGUMENTS
{STATIC_VAR}: {default_value}

## Workflow

1. **{Step Name}** - {description}
2. **{Step Name}** - {description}
3. **{Step Name}** - {description}

## Report

{Output format specification}
```

### Level 3: Control Flow Prompt

```markdown
---
description: {description}
argument-hint: {argument hint}
model: sonnet
allowed-tools: {tools}
---

# {Title}

## Purpose

{Direct statement}

## Variables

{VARIABLE_NAME}: $ARGUMENTS

## Instructions

- If {condition}, {action}
- {constraint or rule}

## Workflow

1. **{Step}**
   - If {condition}: {early return or branch}
   
2. **{Loop Step}**
   - For each {item} in {collection}:
     - {action}
     
3. **{Conditional Step}**
   - If {condition}: {path A}
   - Else: {path B}

## Report

{Output format}
```

### Level 4: Delegation Prompt

```markdown
---
description: {description}
argument-hint: {argument hint}
model: sonnet
allowed-tools: {tools}
---

# {Title}

## Purpose

{Orchestrate sub-agents to accomplish task}

## Variables

TASK: $1
AGENT_COUNT: $2

## Instructions

- Design focused prompts for each sub-agent
- Define clear boundaries and responsibilities
- Specify output expectations for each agent

## Workflow

1. **Analyze Task**
   - Break down into parallelizable subtasks
   - Identify dependencies between subtasks

2. **Design Agent Prompts**
   - Create self-contained prompt for each sub-agent
   - Include: purpose, specific instructions, output format

3. **Spawn Agents**
   - Launch {AGENT_COUNT} agents in parallel
   - Pass designed prompts to each

4. **Collect Results**
   - Wait for all agents to complete
   - Aggregate outputs

5. **Synthesize**
   - Combine results into cohesive output

## Report

## Delegation Report

**Task:** {TASK}
**Agents Spawned:** {count}

| Agent | Focus | Status | Output |
|-------|-------|--------|--------|
| 1 | {focus} | ✅/❌ | {summary} |

**Combined Result:**
{synthesized output}
```

### Level 5: Higher-Order Prompt

```markdown
---
description: {description}
argument-hint: <path-to-input-prompt-or-plan>
model: sonnet
allowed-tools: {tools}
---

# {Title}

## Purpose

{Execute/process the provided prompt or plan}

## Variables

INPUT_PATH: $ARGUMENTS
{additional static vars}

## Instructions

- Read and parse the input prompt/plan
- Execute according to its structure
- Adapt to the input's specific requirements

## Workflow

1. **Load Input**
   - Read {INPUT_PATH}
   - Parse structure and requirements

2. **Validate**
   - Ensure input is well-formed
   - If invalid: stop and report issues

3. **Execute**
   - Follow the input's workflow/plan
   - Apply any transformations needed

4. **Report**
   - Output in format specified by input
   - Or use default report format

## Report

{Dynamic based on input, or default format}
```

### Level 6: Template Meta-Prompt

```markdown
---
description: {description}
argument-hint: <high-level description of prompt to generate>
model: sonnet
allowed-tools: Read, Write
---

# {Title}

## Purpose

Generate a new {type} prompt based on the provided description.

## Variables

PROMPT_DESCRIPTION: $ARGUMENTS
OUTPUT_FORMAT: {specified format}

## Documentation

Reference these for context:
- {path/to/relevant/examples}
- {path/to/style/guide}

## Instructions

- Follow the specified format exactly
- Use direct tone of voice
- Include only necessary sections
- Generate both metadata and content files

## Workflow

1. **Analyze Request**
   - Parse the prompt description
   - Identify required sections

2. **Research Context**
   - Read documentation references
   - Understand existing patterns

3. **Generate Prompt**
   - Create metadata (.yaml)
   - Create content (.prompt.v1.md)
   - Follow specified format

4. **Validate**
   - Ensure all required sections present
   - Check for consistency

## Specified Format

{The exact template/structure to generate}

## Report

Created: {path to new prompt}
```

### Level 7: Self-Improving Prompt

```markdown
---
description: {description}
argument-hint: {argument hint}
model: sonnet
allowed-tools: {tools}
---

# {Title}

## Purpose

{Core purpose that remains stable}

## Variables

{vars}

## Expertise

{Dynamic section that gets updated based on learning}

Current expertise:
- {learned pattern 1}
- {learned pattern 2}

## Instructions

- Apply current expertise to the task
- Identify new patterns during execution
- Update expertise section with learnings

## Workflow

1. **Apply Expertise**
   - Use current knowledge
   
2. **Execute Task**
   - {core workflow}

3. **Learn**
   - Identify patterns that worked/didn't work
   - Note improvements for future

4. **Update**
   - Propose updates to expertise section

## Report

{output + learning summary}
```

## Report

## Prompt Generated

**Level:** {LEVEL}
**ID:** {PROMPT_ID}
**Category:** {CATEGORY}

**Files Created:**
- `{OUTPUT_DIR}/{CATEGORY}/{PROMPT_ID}/{PROMPT_ID}.yaml`
- `{OUTPUT_DIR}/{CATEGORY}/{PROMPT_ID}/{PROMPT_ID}.prompt.v1.md`

**Sections Included:**
{list of sections in the generated prompt}

## Examples

### Example 1: Generate a Level 2 workflow prompt
```
/prompt-generator 2 "Analyze git history and summarize recent changes"
```

### Example 2: Generate a Level 4 delegation prompt
```
/prompt-generator 4 "Research a topic using multiple parallel agents"
```

### Example 3: Generate a Level 6 template meta-prompt
```
/prompt-generator 6 "Generate API endpoint documentation"
```
