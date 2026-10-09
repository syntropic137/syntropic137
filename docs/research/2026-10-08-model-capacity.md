# Model capacity across multiple AI subscriptions and accounts

Date: 2026-10-08. Status: research, input to #1612 ("provider account
ownership", "model-provider limits") and #1718. Docs only, no code changes,
no issues filed. Plan: research run exec-fb867b95771f (revise phase,
codex-reviewed). Code citations are against `origin/main` at `38d4db687`.

Question: can the platform reach 100 concurrent executions (then 1,000) by
spreading runs across several AI subscriptions or accounts? If not, what is
the compliant route, and what does it cost?

**Short answer.**

- The Anthropic pages fetched for this document state, verbatim, that
  subscription (OAuth) credentials are "designed to support ordinary use",
  that "Advertised usage limits for Pro and Max plans assume ordinary,
  individual usage", and that Anthropic does not permit developers "to route
  requests through Free, Pro, or Max plan credentials on behalf of their
  users" (section 1.2). On those quotes, stacking several personal Pro or Max
  subscriptions behind an automated platform to raise its capacity is
  **likely outside the consumer terms**. Nothing fetched says it is
  permitted. This document does not conclude permission from a plan name.
- OpenAI's Terms of Use returned 403 to curl; an Internet Archive capture
  of the same URL from 2026-10-08 was fetched instead, and says "You may not
  share your account credentials or make your account available to anyone
  else" and forbids attempts to "circumvent any rate limits or
  restrictions" (section 1.3). The Service and Business Terms stay
  **UNVERIFIED**.
- Both providers document headless use of a subscription login by its own
  licensee (Claude Code's `claude setup-token` "for CI pipelines and
  scripts"; Codex's ChatGPT-managed auth in CI/CD, an "advanced" path). That
  is not permission to pool subscriptions or to run one login across many
  concurrent workspaces, and OpenAI says "Do not share the same file across
  concurrent jobs or multiple machines" (section 1.5).
- The routes the fetched pages describe for automated, organization-level
  use are API keys under the Commercial Terms (Anthropic, OpenAI), cloud
  marketplaces (Bedrock, Vertex), and usage-based Enterprise plans billed at
  API rates.
- Cost at API rates, from the owner's per-run estimate: **$75 to $1,200 per
  hour at 100 concurrent, $750 to $12,000 per hour at 1,000** (estimate,
  section 2). At the top of that range, a continuously busy 100 exceeds the
  Anthropic API's highest self-serve monthly spend cap ($200,000) and needs
  the Custom tier.
- Provider capacity alone does not deliver 100: the shared Envoy bucket and
  the single-host executor are platform limits no purchase fixes (section
  2.6).

Every section separates **what exists today**, **what is proposed**, and
**what is unverified**.

## 1. Provider facts

All pages below were fetched with `curl` on 2026-10-08 ("accessed
2026-10-08"). Quotes are verbatim and in block quotes, with the source's own
punctuation, typographic apostrophes and quotation marks included. The only
change made inside a quote is layout whitespace: where the page renders an
inline code span or a line break inside a sentence, the pieces are joined
with a single space. Any omitted material, including every passage that
contains an em dash on the source page, is replaced by a visible `[...]`.
A quote marked "excerpt" is not the whole paragraph. Anything not fetched is
marked **UNVERIFIED** and kept out of section 2's arithmetic.

### 1.1 Fetch log

| Page | URL | Result |
|---|---|---|
| Anthropic Consumer Terms (effective October 8, 2025) | https://www.anthropic.com/legal/consumer-terms | 200 |
| Anthropic Commercial Terms (effective June 17, 2025) | https://www.anthropic.com/legal/commercial-terms | 200 |
| Anthropic Usage Policy (page shows "Effective November 12, 2026") | https://www.anthropic.com/legal/aup | 200 |
| Claude Code, Legal and compliance | https://docs.claude.com/en/docs/claude-code/legal-and-compliance | 200 |
| Use Claude Code with your Pro or Max plan | https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan | 200 |
| Use Claude Code with your Team or Enterprise plan | https://support.claude.com/en/articles/11845131-using-claude-code-with-your-team-or-enterprise-plan | 200 |
| About Claude's Max plan usage | https://support.claude.com/en/articles/11014257-about-claude-s-max-plan-usage | **404, UNVERIFIED** |
| Claude plans and prices | https://claude.com/pricing | 200 |
| Claude API rate limits | https://docs.claude.com/en/api/rate-limits | 200 |
| Claude API pricing | https://docs.claude.com/en/docs/about-claude/pricing | 200 |
| Amazon Bedrock quotas (user guide) | https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html | 200 |
| Amazon Bedrock service quotas (general reference) | https://docs.aws.amazon.com/general/latest/gr/bedrock.html | 200 |
| Vertex AI, Claude models | https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude/use-claude | 200, but no default quota values found on it: **UNVERIFIED** |
| Claude Code, Authentication | https://code.claude.com/docs/en/authentication | 200 |
| Claude Code, Run Claude Code programmatically | https://code.claude.com/docs/en/headless | 200 |
| Amazon Bedrock pricing | https://aws.amazon.com/bedrock/pricing/ | 200, but the Anthropic price values are not in the static page (column headers only): **UNVERIFIED** |
| Vertex AI generative AI pricing | https://cloud.google.com/vertex-ai/generative-ai/pricing | 200 |
| OpenAI Terms of Use | https://openai.com/policies/terms-of-use/ (also `/row-terms-of-use/`, `/en-GB/policies/terms-of-use/`) | **403** to curl |
| OpenAI Terms of Use, Internet Archive capture of the same URL taken 2026-10-08 16:38:31 UTC | https://web.archive.org/web/20261008163831/https://openai.com/policies/terms-of-use/ | 200 (page shows "Effective: January 1, 2026") |
| OpenAI Service Terms | https://openai.com/policies/service-terms/ | **403, UNVERIFIED** |
| OpenAI Business Terms | https://openai.com/policies/business-terms/ | **403, UNVERIFIED** |
| Using Codex with your ChatGPT plan | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan | **403, UNVERIFIED** |
| Codex pricing and plan limits | https://developers.openai.com/codex/pricing | 200 |
| Codex, Non-interactive mode | https://developers.openai.com/codex/noninteractive | 200 |
| Codex, Maintain Codex account auth in CI/CD | https://developers.openai.com/codex/auth/ci-cd-auth | 200 |
| OpenAI API rate limits | https://platform.openai.com/docs/guides/rate-limits | 200 |
| OpenAI GPT-6.1 Sol model page | https://developers.openai.com/api/docs/models/gpt-6.1-sol | 200 |

### 1.2 Anthropic terms, quoted

**Consumer Terms**, section "Account" (https://www.anthropic.com/legal/consumer-terms, accessed 2026-10-08):

> You may not share your Account login information, Anthropic API key, or Account credentials with anyone else. You also may not make your Account available to anyone else. You are responsible for all activity occurring under your Account, and you agree to notify us immediately if you become aware of any unauthorized access to your Account by sending an email to support@anthropic.com.

**Consumer Terms**, from the list introduced by "You may not access or use, or help another person to access or use, our Services in the following ways:" (same URL, accessed 2026-10-08):

> Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it, to access the Services through automated or non-human means, whether through a bot, script, or otherwise.

**Consumer Terms**, scope note (same URL, accessed 2026-10-08):

> Please note: Our Commercial Terms of Service govern your use of any Anthropic API key, the Anthropic Console, or any other Anthropic offerings that reference the Commercial Terms of Service. For clarity, this does not include Claude.ai or Claude Pro use for individuals or entities.

**Claude Code, Legal and compliance**, "License" (https://docs.claude.com/en/docs/claude-code/legal-and-compliance, accessed 2026-10-08):

> Your use of Claude Code is subject to:
> Commercial Terms of Service - for Team, Enterprise, and Claude API users
> Consumer Terms of Service - for Free, Pro, and Max users

**Same page**, "Acceptable use":

> Claude Code usage is subject to the Anthropic Usage Policy. Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK.

**Same page**, "Authentication and credential use" (excerpt: the section's first three paragraphs; the last sentence of the OAuth paragraph, a pointer to the sign-in pages, is omitted, and the third paragraph's last sentence is cut where the source page has an em dash):

> Claude Code authenticates with Anthropic’s servers using OAuth tokens or API keys. These authentication methods serve different purposes:
>
> OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications. [...]

> Developers building products or services that interact with Claude’s capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens [...]

**Same page**, the paragraph that follows it:

> This does not restrict how customers provision and manage their own API keys or third-party inference provider credentials [...] provided the resulting usage is billed to the key owner under their agreement with Anthropic (or the applicable provider) and is not resold or intermediated as described above. Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code as described under Can customers offer Claude Code in their products? above.
>
> Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice.
>
> For questions about permitted authentication methods for your use case, please contact sales.

**Same page**, "Can customers offer Claude Code in their products?" (excerpt: the opening sentence and the second of the listed conditions; the first condition, on not modifying the binary, and the third, on names and logos, are omitted):

> Unless we’ve mutually agreed otherwise, preinstalling or running Claude Code in your products or services (e.g. in hosted sandboxes or other agent infrastructure) requires agreeing to our Commercial Terms of Service and complying with the conditions below:

> [...]
>
> Customers may not pay for, resell, or intermediate Claude usage on their end users’ behalf. Each end user must authenticate with their own Anthropic API key, Claude subscription plan credentials, or 3P inference provider credential (Amazon Bedrock, Google Cloud’s Agent Platform, Microsoft Foundry). That usage is billed directly to the end user under their own agreement with Anthropic or, for third-party inference providers, with the applicable provider.

**Same page**, "Commercial agreements":

> Whether you’re using the Claude API directly (1P) or accessing it through Amazon Bedrock or Google Cloud’s Agent Platform (3P), your existing commercial agreement will apply to Claude Code usage, unless we’ve mutually agreed otherwise.

**Usage Policy**, under "Do Not Abuse Our Platform" (https://www.anthropic.com/legal/aup, accessed 2026-10-08; the page header reads "Effective November 12, 2026"):

> Coordinate malicious activity across multiple accounts, or create multiple accounts, to avoid detection, circumvent product guardrails, or generate identical or similar inputs that otherwise violate our Usage Policy

The Usage Policy does not say, in what was fetched, whether a usage limit is a "product guardrail". This document does not read it as covering usage limits; the anti-circumvention question for Anthropic rests on the Consumer Terms and Claude Code quotes above, not on this line.

**Commercial Terms**, D.4 (https://www.anthropic.com/legal/commercial-terms, accessed 2026-10-08):

> D.4. Use Restrictions. Customer may not and must not attempt to (a) access the Services to build a competing product or service, including to train competing AI models or resell the Services except as expressly approved by Anthropic; (b) reverse engineer or duplicate the Services; or (c) support any third party’s attempt at any of the conduct restricted in this sentence.

No Commercial Terms clause on rate-limit circumvention or on automated access was found by searching the fetched text for "circumvent", "rate limit" and "usage limit".

**Claude Code, Authentication**, "Generate a long-lived token" (https://code.claude.com/docs/en/authentication, accessed 2026-10-08; excerpt: the paragraph's opening, then the paragraph after the shell examples):

> For CI pipelines, scripts, or other environments where interactive browser login isn’t available, generate a one-year OAuth token with claude setup-token:

> [...]
>
> This token authenticates with your Claude subscription and requires a Pro, Max, Team, or Enterprise plan. It can only make model requests, so it can’t establish Remote Control sessions or fetch claude.ai connectors. MCP servers you configure locally still work.

**Same page**, "Authentication precedence" (excerpt: the list's lead-in and the `CLAUDE_CODE_OAUTH_TOKEN` item; the other items are omitted):

> When multiple credentials are present, Claude Code chooses one in this order:
>
> [...]
>
> CLAUDE_CODE_OAUTH_TOKEN environment variable. A long-lived OAuth token generated by claude setup-token. Use this for CI pipelines and scripts where browser login isn’t available.

**Claude Code, Run Claude Code programmatically** (https://code.claude.com/docs/en/headless, accessed 2026-10-08; excerpt):

> To run Claude Code in non-interactive mode, pass -p with your prompt and the CLI options you need:

**Same site, Authentication page**, on bare mode (excerpt):

> Bare mode does not read CLAUDE_CODE_OAUTH_TOKEN. If your script passes --bare, authenticate with ANTHROPIC_API_KEY or an apiKeyHelper instead.

These pages document headless use of a subscription token by its licensee
("CI pipelines and scripts"). They are product documentation, not terms, and
none of them mentions concurrency, several workspaces, or a platform running
the token on someone's behalf. Section 1.5 reads them together with the
Consumer Terms and Claude Code legal quotes.

### 1.3 OpenAI terms and Codex automation

**Terms of Use.** The live page returned 403 to curl. The quotes below are
from the Internet Archive capture of the same URL taken on 2026-10-08 at
16:38:31 UTC
(https://web.archive.org/web/20261008163831/https://openai.com/policies/terms-of-use/,
accessed 2026-10-08), which shows "Effective: January 1, 2026". They are a
third-party copy, so a reviewer with a browser should re-open the live page
before a decision rests on them. The Service Terms, Business Terms and the
Codex-with-ChatGPT help article stay **UNVERIFIED** (403, section 1.1).

"Registration and access", "Registration" (excerpt: the third sentence is omitted):

> Registration. You must provide accurate and complete information to register for an account to use our Services. You may not share your account credentials or make your account available to anyone else and are responsible for all activities that occur under your account. [...]

"Using our Services", "What you cannot do" (excerpt: the lead-in and the item on rate limits; the other items are omitted):

> What you cannot do. You may not use our Services for any illegal, harmful, or abusive activity. For example, you may not:
>
> [...]
>
> Interfere with or disrupt our Services, including circumvent any rate limits or restrictions or bypass any protective measures or safety mitigations we put on our Services.

These are the Terms of Use. Which OpenAI terms govern a ChatGPT Business or
Enterprise workspace, or the API, is in the Service and Business Terms,
which are **UNVERIFIED** here.

**Codex pricing page** (https://developers.openai.com/codex/pricing, accessed 2026-10-08), next to the "API Key" option:

> Great for automation in shared environments like CI.

**Codex, Non-interactive mode**, "Use ChatGPT-managed auth in CI/CD (advanced)" (https://developers.openai.com/codex/noninteractive, accessed 2026-10-08):

> Read this if you need to run CI/CD jobs with a Codex user account instead of an API key, such as enterprise teams using ChatGPT-managed Codex access on trusted runners or users who need ChatGPT/Codex rate limits instead of API key usage.
>
> API keys are the right default for automation because they are simpler to provision and rotate. Use this path only if you specifically need to run as your Codex account.

**Codex, Maintain Codex account auth in CI/CD** (https://developers.openai.com/codex/auth/ci-cd-auth, accessed 2026-10-08; excerpts):

> This is an advanced workflow for enterprise and other trusted private automation. API keys are still the recommended option for most CI/CD jobs.

> Use one auth.json per runner or per serialized workflow stream.
>
> Do not share the same file across concurrent jobs or multiple machines.

These are product documentation, not terms. They document that one Codex
user may run their own ChatGPT-managed login in automation, as an advanced
path, and they say plainly that one `auth.json` must not be shared across
concurrent jobs.

### 1.4 Terms by usage pattern

Each cell is a literal excerpt from a quote in 1.2 or 1.3 (same URL and
access date), or **UNVERIFIED**. The cells are evidence only; what this
document reads into them is in the "Interpretation" list under the table,
labelled as interpretation.

| Pattern | Anthropic (Pro/Max) | Anthropic (Team / Enterprise seats) | Anthropic (API key, Bedrock, Vertex) | OpenAI (Codex, ChatGPT plans) | OpenAI (API key) |
|---|---|---|---|---|---|
| Supported CLI automation by its licensee | "For CI pipelines, scripts, or other environments where interactive browser login isn’t available, generate a one-year OAuth token"; "This token authenticates with your Claude subscription and requires a Pro, Max, Team, or Enterprise plan." | same two excerpts (they name Team and Enterprise) | "Developers building products or services that interact with Claude’s capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider." | "Read this if you need to run CI/CD jobs with a Codex user account instead of an API key"; "Use this path only if you specifically need to run as your Codex account." | "Great for automation in shared environments like CI."; "API keys are the right default for automation" |
| One person's login used by a platform | "developers may not collect, store, or intermediate Claude.ai credentials or session tokens"; "Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code" | same excerpts | "This does not restrict how customers provision and manage their own API keys or third-party inference provider credentials" | "Do not share the same file across concurrent jobs or multiple machines." | **UNVERIFIED** |
| Many personal subscriptions pooled | "You may not share your Account login information, Anthropic API key, or Account credentials with anyone else. You also may not make your Account available to anyone else."; "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users." | **UNVERIFIED** | n/a | "You may not share your account credentials or make your account available to anyone else" (Terms of Use, archive capture) | n/a |
| Per-user seat assignment | n/a | "This article applies to members of Team or Enterprise plan organizations" (scope line of the Team page only) | n/a | "$20/ user / month*" (Business price; terms **UNVERIFIED**) | n/a |
| Organization-level capacity | n/a | "If your organization is on a usage-based Enterprise plan (including self-serve Enterprise), there are no per-seat usage limits [...] usage is based on consumption and billed at API rates." | "Limits are set at the organization level." | "no fixed rate limits. Usage scales with credits." (Enterprise/Edu with flexible pricing) | "Rate limits are defined at the organization level and at the project level, not user level." |
| Multi-account to exceed a limit | "create multiple accounts, to avoid detection, circumvent product guardrails, or generate identical or similar inputs that otherwise violate our Usage Policy" (Usage Policy) | **UNVERIFIED** | **UNVERIFIED** | "circumvent any rate limits or restrictions" (Terms of Use, archive capture) | same Terms of Use excerpt; whether the API is governed by these terms or by Service/Business Terms: **UNVERIFIED** |

The usage-based Enterprise quote, cut at the em dash on the source page
(https://support.claude.com/en/articles/11845131-using-claude-code-with-your-team-or-enterprise-plan, accessed 2026-10-08):

> If your organization is on a usage-based Enterprise plan (including self-serve Enterprise), there are no per-seat usage limits [...] usage is based on consumption and billed at API rates.

**Interpretation (this document's reading, not a quote):**

- *Supported licensee automation exists on both sides.* Anthropic documents
  a subscription OAuth token "for CI pipelines and scripts", and OpenAI
  documents ChatGPT-managed Codex auth in CI as an advanced path. Neither
  page is a terms clause, and neither mentions concurrency or a platform
  running the credential for someone else. A documented CLI flag is not a
  grant of permission for this platform's use.
- *Many personal subscriptions pooled* behind one automated service is
  likely outside both providers' terms on the quoted sharing clauses, and on
  Anthropic's "route requests through Free, Pro, or Max plan credentials on
  behalf of their users" sentence.
- *Team/Enterprise seats are not blanket permission.* The only seat text
  fetched scopes the article to "members"; nothing fetched says whether one
  automated service may run through many members' seats.
- *Multi-account to exceed a limit:* OpenAI's Terms of Use name rate limits
  explicitly. Anthropic's Usage Policy line names "product guardrails"; it
  does not say whether a usage limit is one, so this document does not read
  it as covering usage limits.

### 1.5 What this means for today's single-token use

**Exists today.** The platform injects one Claude OAuth token into every
agent workspace
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:242-255`),
and the code's only stated basis is an unsourced note, "OAuth is out of scope
(ToS gray area for header proxying)"
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:251`;
`docs/adrs/ADR-024-setup-phase-secrets.md:531`). Codex runs on one
`auth.json` copied into every workspace that needs it
(`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:731-751`).

**What the quotes establish.** Three things are kept apart:

1. *Supported automation by the licensee.* Both providers document running
   their own CLI headless on the licensee's own subscription login: Claude
   Code's `claude setup-token` token "for CI pipelines and scripts", read in
   `-p` (non-bare) mode, and Codex's ChatGPT-managed auth in CI/CD, which
   OpenAI calls an advanced path and says to "Use this path only if you
   specifically need to run as your Codex account". So one owner running
   their own subscription headless is a documented use, on these pages.
2. *Many people's subscriptions pooled behind a service.* Not covered by
   that documentation and likely outside the quoted sharing clauses (1.4).
3. *Third-party hosted authentication.* Anthropic's legal page says
   developers "may not collect, store, or intermediate Claude.ai credentials
   or session tokens", and that hosting Claude Code in "hosted sandboxes or
   other agent infrastructure" requires the Commercial Terms unless agreed
   otherwise.

**What remains unresolved for many concurrent workspaces.** None of the
fetched pages says whether one licensee's subscription token may drive many
concurrent automated workspaces on a platform the licensee operates. The
Claude Code page says subscription limits "assume ordinary, individual
usage", and its own answer for edge cases is "please contact sales". For
Codex the documentation is more specific and runs against the current
design: "Do not share the same file across concurrent jobs or multiple
machines", while the platform copies one `auth.json` into every concurrent
workspace (see 3.10). The owner should treat the current single-token
posture as **unresolved for Claude and contrary to OpenAI's documented
operational rule for Codex**, not as permitted, and the "gray area" note
should be replaced with these quotes (follow-up, not this PR).

**Compliant routes the quotes describe:** an Anthropic API key under the
Commercial Terms; Bedrock or Vertex under the existing commercial agreement;
a usage-based Enterprise plan billed at API rates; an explicit arrangement
with Anthropic sales. For OpenAI: an API key, which its documentation calls
"the right default for automation" (organization or project limits).
Whether ChatGPT Enterprise with flexible pricing permits automated platform
use is **UNVERIFIED** (Service and Business Terms returned 403).

### 1.6 Limits and prices, sourced

Subscription windows (https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan, accessed 2026-10-08):

> Both Pro and Max plans have a five-hour session limit and a weekly limit. Max plans also have a separate weekly limit for Fable. These limits are shared across Claude and Claude Code, meaning all activity in both tools counts against the same limits.

No fetched page gives those windows as numbers. Max 5x versus 20x usage
amounts: **UNVERIFIED** (the Max usage article returned 404).

Codex plan limits (https://developers.openai.com/codex/pricing, accessed 2026-10-08):

> The estimates below show local messages per five-hour period for Plus and
> Standard Business. Pro plans currently have no five-hour limit.

> Local messages and cloud chats share your plan’s usage allowance. Weekly
> limits may also apply.

> Enterprise and Edu plans without flexible pricing have the same per-seat
> usage limits as Plus for most features.

| Item | Value | Source (accessed 2026-10-08) |
|---|---|---|
| Claude Max | "From $100 Per month"; 20x price not shown | https://claude.com/pricing |
| Claude Team standard seat | "$20 Per seat / month if billed annually. $25 if billed monthly." | https://claude.com/pricing |
| Claude Team premium seat | "$100 Per seat / month if billed annually. $125 if billed monthly." | https://claude.com/pricing |
| Claude Enterprise | "Seat price + usage at API rates"; "US$20/seat/month, billed annually." | https://claude.com/pricing |
| ChatGPT Plus | "$20/month" | https://developers.openai.com/codex/pricing |
| ChatGPT Pro | "Plans at $100, $200, or $500 USD per month" | https://developers.openai.com/codex/pricing |
| ChatGPT Business | "$20/ user / month*" (footnote not captured) | https://developers.openai.com/codex/pricing |
| Claude Opus 5.5 API | $4 input, $20 output, $5 5-minute cache write, $0.20 cache hit, per MTok | https://docs.claude.com/en/docs/about-claude/pricing |
| Claude Sonnet 5.5 API | $2 input, $10 output, $2.50 5-minute cache write, $0.10 cache hit, per MTok | same |
| GPT-6.1-Sol API, Standard | Input "$2.00", Cached input "$0.10", Cache writes "$2.50", Output "$10.00", per 1M text tokens | https://developers.openai.com/api/docs/models/gpt-6.1-sol |
| Claude Sonnet 5.5 on Vertex AI | Input "$2.00", Output "$10.00", 5m Cache Write "$2.50", Cache Hit "$0.10" (first table); a later table on the page shows "$2.20", "$11.00", "$2.75", "$0.11" | https://cloud.google.com/vertex-ai/generative-ai/pricing |
| Claude Opus 5.5 on Vertex AI | Input "$4.00", Output "$20.00", 5m Cache Write "$5.00", Cache Hit "$0.20" (first table); the later table shows "$4.40", "$22.00" for input and output | same |
| Claude on Amazon Bedrock | **UNVERIFIED**: the page's Anthropic table headers were fetched, its values were not in the static page | https://aws.amazon.com/bedrock/pricing/ |

GPT-6.1-Sol pricing modifiers, from the same model page:

> Prompts with more than 272K input tokens are priced at 2x input and cache rates and 1.5x output for the full request.

> Fast mode prices are 2x Standard. Batch and Flex prices are 50% lower than Standard.

> Ultrafast mode prices are 6x Standard.

> Regional processing adds a 10% premium where available.

The fetched GPT-6.1-Sol Standard rates match
`packages/syn-shared/src/syn_shared/pricing/__init__.py:239-252`, whose comment
also records the 272K long-context rule and says that tier is not modelled.

Vertex: the page lists its Claude prices under "Models with regional
pricing", with region tabs beginning "Global", "US Multi-Region (US)", "EU
Multi-Region (EU)". From the static page this document could not establish
which tab each repeated table belongs to, so it records only that the first
table equals the Anthropic API rates and a later one is 10% higher.

The fetched Claude prices match the repository table
(`packages/syn-shared/src/syn_shared/pricing/__init__.py:210-237`). The
pricing page's table now shows $0.10 for a Sonnet 5.5 cache hit, which
settles the disagreement the comment at
`packages/syn-shared/src/syn_shared/pricing/__init__.py:225-229` records, in
the same direction the code chose.

**Anthropic API rate limits** (https://docs.claude.com/en/api/rate-limits, accessed 2026-10-08):

> Limits are set at the organization level. You can see your organization's tier and current limits on the Rate limits page in the Claude Console.

> The API uses the token bucket algorithm to do rate limiting. This means that your capacity is continuously replenished up to your maximum limit, rather than being reset at fixed intervals.

> For rate limit purposes on most models, only input_tokens + cache_creation_input_tokens count toward your ITPM limit, making prompt caching an effective way to increase your effective throughput.

> Organization-wide limits always apply, even if Workspace limits add up to more.

| Tier | Monthly spend cap | Opus 5.5 RPM / ITPM / OTPM | Sonnet 5.5 RPM / ITPM / OTPM |
|---|---|---|---|
| Start | $500 | 1,000 / 2,000,000 / 400,000 | 1,000 / 2,000,000 / 400,000 |
| Build | $1,000 | 5,000 / 5,000,000 / 1,000,000 | 5,000 / 5,000,000 / 1,000,000 |
| Scale | $200,000 | 10,000 / 10,000,000 / 2,000,000 | 10,000 / 10,000,000 / 2,000,000 |
| Custom | "no monthly spend cap; limits are arranged with their account team" | by arrangement | by arrangement |

The page also says new organizations "may start in the Evaluation tier, with
limits below the standard limits", and that response headers
`anthropic-ratelimit-requests-remaining`, `anthropic-ratelimit-tokens-remaining`
and related ones are returned on API responses. Whether those headers appear
on **subscription (OAuth)** traffic: **UNVERIFIED**.

Tier advancement and higher limits, same page:

> Limits are defined by usage tier. Organizations are placed on a tier automatically based on usage history and account standing and can move to a higher tier over time as they use the API.

> To request higher rate limits or a higher monthly spend cap, use Request tier increase on the Rate limits page.

**Amazon Bedrock** (https://docs.aws.amazon.com/general/latest/gr/bedrock.html, accessed 2026-10-08): "Cross-region model inference tokens per minute for Anthropic Claude Opus 5.5", "Each supported Region: 30,000,000", adjustable "Yes"; the same for Sonnet 5.5 is "Each supported Region: 6,000,000", adjustable "Yes". "On-demand model inference tokens per minute for Anthropic Claude Opus 5.5" is "Each supported Region: 15,000,000", adjustable "No". The quota "considers the combined sum of input and output tokens across all requests to Converse, ConverseStream, InvokeModel and InvokeModelWithResponseStream". Whether cache reads count toward it: **UNVERIFIED**. No requests-per-minute quota for Claude Opus 5.5 or Sonnet 5.5 was found in the fetched reference: **UNVERIFIED**. From the user guide (https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html):

> Quota increases aren't granted automatically.

**Google Vertex AI:** default Claude quotas **UNVERIFIED** (the fetched page
links to a quotas page whose values were not captured).

**OpenAI API** (https://platform.openai.com/docs/guides/rate-limits, accessed 2026-10-08):

> Rate limits are defined at the organization level and at the project level, not user level.

| Tier | Qualification | Usage limit |
|---|---|---|
| Build | $5 in total credit purchases | $500 / month |
| Launch | $100 in total credit purchases | $5,000 / month |
| Grow | $500 in total credit purchases | $200,000 / month |

> Your organization’s usage tier upgrades automatically as its total credit purchases reach each threshold.

How the token rate limit is counted (same page):

> Your rate limit is calculated as the maximum of max_tokens and the estimated number of tokens based on the character count of your request.

Whether cached input is excluded from that count is not stated on the
fetched page: **UNVERIFIED**. How to exceed Grow's $200,000/month usage
limit is not stated in what was fetched: **UNVERIFIED**.

GPT-6.1-Sol per-tier limits (https://developers.openai.com/api/docs/models/gpt-6.1-sol, accessed 2026-10-08):

| Tier | RPM | TPM |
|---|---|---|
| Build | 5,000 | 1,000,000 |
| Launch | 10,000 | 4,000,000 |
| Grow | 15,000 | 40,000,000 |

## 2. Arithmetic

Every number here is an **estimate** unless it carries a section 1 source.

### 2.1 Inputs

| Symbol | Value | Status |
|---|---|---|
| *C*, cost per workflow execution (run) | implement-v3 $3 to 12, reverify $3 to 9; range used: $3 to $12 | owner-provided, API-equivalent estimate |
| *D*, active duration of a run | 1 to 4 h | assumption, not measured (`docs/north-star.md:71`) |
| *N* | 100 and 1,000 concurrent runs | north star |

Real execution durations were not readable from this workspace, so *D*
stays the north star's assumption. If *C* turns out to be per phase rather
than per run, every row below must be recomputed per phase.

### 2.2 Dollars per hour: $/h = N x C / D

| N | Low (C = $3, D = 4 h) | High (C = $12, D = 1 h) | Per month, 8 h/day x 30 | Per month, 24 h/day x 30 |
|---|---|---|---|---|
| 100 | $75/h | $1,200/h | $18,000 to $288,000 | $54,000 to $864,000 |
| 1,000 | $750/h | $12,000/h | $180,000 to $2,880,000 | $540,000 to $8,640,000 |

All estimates. Spend is checked here; rate limits are checked separately
in 2.6, and the two verdicts are independent.

Against section 1.6: a $200,000 monthly cap (Anthropic Scale; OpenAI Grow
uses the same figure) holds while $/h x hours per month <= $200,000, that is
while N x C / D <= $833/h at 8 h/day x 30 (240 h), or <= $278/h at 24 h/day
x 30 (720 h). Read against the table:

| N | 8 h/day x 30 | 24 h/day x 30 |
|---|---|---|
| 100 | within the cap at the low end ($18,000); above it from $833/h up, so the high end ($288,000) needs a higher negotiated limit | within the cap at the low end ($54,000); above it from $278/h up, so the high end ($864,000) needs a higher limit |
| 1,000 | within the cap at the low end ($180,000 < $200,000); above it from $833/h up, so the high end ($2,880,000) needs a higher limit | above the cap across the whole range ($540,000 to $8,640,000) |

"A higher limit" means Anthropic's Custom tier ("no monthly spend cap;
limits are arranged with their account team") or a requested increase; for
OpenAI, how to exceed Grow is **UNVERIFIED** (1.6).

### 2.3 Tokens, by declared mix

No blended price without a mix. Each scenario assumes the same token mix,
chosen as an **assumption** for a long agentic run with heavy prompt caching:
90% cache read, 3% cache write, 5% uncached input, 2% output.

**Pricing regime (assumption):** each provider's Standard, on-demand,
non-batch rate from section 1.6, with 5-minute cache writes for Claude. For
GPT-6.1-Sol this is the short-context rate: every request is assumed to
stay at or under 272K input tokens, and Fast, Ultrafast, Batch, Flex and
regional processing are not used. A request above 272K input is billed at
"2x input and cache rates and 1.5x output for the full request" (1.6), so a
long-context run buys fewer tokens per dollar than shown. The token volumes
below are derived from Anthropic API and OpenAI API prices; they describe
the workload, and are reused unchanged for Bedrock and Vertex in 2.6.

| Scenario | Prices used (per MTok) | Effective $/MTok = sum(share x price) | MTok per run at C = $3 / $12 |
|---|---|---|---|
| A. Sonnet 5.5 | 0.10 / 2.50 / 2 / 10 | 0.9x0.10 + 0.03x2.50 + 0.05x2 + 0.02x10 = 0.465 | 6.45 / 25.81 |
| B. Opus 5.5 | 0.20 / 5 / 4 / 20 | 0.18 + 0.15 + 0.20 + 0.40 = 0.93 | 3.23 / 12.90 |
| C. Codex, GPT-6.1-Sol | 0.10 / 2.50 / 2 / 10 | 0.465 (same rates as A) | 6.45 / 25.81 |

Tokens per minute = ($/h / 60) / effective $/MTok. Rate-limit-counted input
(Anthropic ITPM) = uncached input + cache write = 8% of the total; output
(OTPM) = 2%.

Per minute:

| Scenario | N | $/min | Total MTok/min | Excluding cache reads (10%) | ITPM-counted MTok/min | OTPM MTok/min |
|---|---|---|---|---|---|---|
| A. Sonnet 5.5 | 100 | 1.25 to 20 | 2.69 to 43.0 | 0.27 to 4.30 | 0.22 to 3.44 | 0.05 to 0.86 |
| A. Sonnet 5.5 | 1,000 | 12.5 to 200 | 26.9 to 430 | 2.69 to 43.0 | 2.15 to 34.4 | 0.54 to 8.60 |
| B. Opus 5.5 | 100 | 1.25 to 20 | 1.34 to 21.5 | 0.13 to 2.15 | 0.11 to 1.72 | 0.03 to 0.43 |
| B. Opus 5.5 | 1,000 | 12.5 to 200 | 13.4 to 215 | 1.34 to 21.5 | 1.08 to 17.2 | 0.27 to 4.30 |
| C. GPT-6.1-Sol | 100 | 1.25 to 20 | 2.69 to 43.0 | 0.27 to 4.30 | n/a (Anthropic ITPM rule) | 0.05 to 0.86 |
| C. GPT-6.1-Sol | 1,000 | 12.5 to 200 | 26.9 to 430 | 2.69 to 43.0 | n/a | 0.54 to 8.60 |

Per hour (60 x the per-minute values):

| Scenario | N | $/h | Total MTok/h | ITPM-counted MTok/h | Output MTok/h |
|---|---|---|---|---|---|
| A. Sonnet 5.5 | 100 | 75 to 1,200 | 161 to 2,581 | 12.9 to 206 | 3.23 to 51.6 |
| A. Sonnet 5.5 | 1,000 | 750 to 12,000 | 1,613 to 25,806 | 129 to 2,065 | 32.3 to 516 |
| B. Opus 5.5 | 100 | 75 to 1,200 | 80.6 to 1,290 | 6.45 to 103 | 1.61 to 25.8 |
| B. Opus 5.5 | 1,000 | 750 to 12,000 | 806 to 12,903 | 64.5 to 1,032 | 16.1 to 258 |
| C. GPT-6.1-Sol | 100 | 75 to 1,200 | 161 to 2,581 | n/a | 3.23 to 51.6 |
| C. GPT-6.1-Sol | 1,000 | 750 to 12,000 | 1,613 to 25,806 | n/a | 32.3 to 516 |

All estimates. Attempts can change provider and model mid-phase
(`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/AgentExecutionCompletedEvent.py:67-72`),
so a per-workflow mix is itself an estimate until #1716 measures per-phase
usage.

### 2.4 Subscription capacity per seat: not estimated

The observations (Codex at 12% of a weekly window after about a week at 4 to
10 concurrent; four runs killed by one Claude 5-hour window on 2026-10-08)
record peak concurrency, not occupied agent-hours, duty cycle, model or phase
mix. The repository records Codex per-account caps as unknown
(`docs/north-star.md:147`). So this document states **no seat count**.

The measurement that would produce one: quota consumed per active
agent-hour, per window, per model scope, from window readings joined to the
credential each invocation ran under (issues 1 and 5 in section 4).

**Hypothetical only:** if one seat served X = 40 agent-hours per week at this
workload (X is an assumption, not a measurement), then 100 continuous runs
(16,800 agent-hours per week) would need 420 seats, and 1,000 would need
4,200. The figure exists to show the shape of the calculation, not the answer.

### 2.5 Crossover

Break-even runs per seat per month = seat price / C.

| Seat | Price / month (section 1.6) | Break-even at C = $3 | at C = $12 | Runs a seat can actually serve |
|---|---|---|---|---|
| Claude Max (lowest) | $100 | 33.3 | 8.3 | unmeasured |
| Claude Team premium (monthly billing) | $125 | 41.7 | 10.4 | unmeasured |
| ChatGPT Pro | $100 / $200 / $500 | 33.3 / 66.7 / 166.7 | 8.3 / 16.7 / 41.7 | unmeasured |
| ChatGPT Plus or Business | $20 | 6.7 | 1.7 | unmeasured |

The comparison means something only once the last column is measured. And
if section 1's quotes hold (pooling consumer seats for this use is likely
not permitted), the consumer rows are moot: the comparison that matters is
API keys versus usage-based Enterprise versus Bedrock or Vertex. Their costs,
as far as the sources go:

- Anthropic API and usage-based Enterprise: section 2.2 (Enterprise is
  "billed at API rates", plus the seat price in 1.6).
- Vertex: section 2.2 if the first price table in 1.6 applies to the
  chosen region; up to 10% more if the later table does (region mapping
  not established).
- Bedrock: **UNVERIFIED**, because its Claude prices were not extracted
  (1.6). It is not assigned the 2.2 estimate.
- OpenAI API (scenario C): section 2.2 at the short-context Standard rates
  of 2.3; more for any request above 272K input.

### 2.6 Feasibility, not just price

Rate limits only; spend is 2.2, and each row repeats which spend case
applies. Throughput comes from 2.3 (low end = C $3, D 4 h; high end = C $12,
D 1 h). Each route's own counting rule decides which column is "counted":

- Anthropic API: ITPM counts uncached input + cache writes, OTPM counts
  output ("only input_tokens + cache_creation_input_tokens count toward your
  ITPM limit", 1.6).
- Bedrock: one combined figure, "the combined sum of input and output
  tokens". Whether cache reads are part of it is **UNVERIFIED**, so both
  readings are shown: all tokens, and all tokens excluding cache reads.
- Vertex: the requirement is the same as Bedrock's; the quota is
  **UNVERIFIED**.
- OpenAI API: "the maximum of max_tokens and the estimated number of tokens
  based on the character count of your request". Whether cached input is
  excluded is **UNVERIFIED**, so both readings are shown. A large
  `max_tokens` setting raises the counted figure further.

**Requests per minute (assumption):** the north star's estimate is 3 to 10
requests per second at 100 on the Envoy (Claude) path
(`docs/north-star.md:167`). This document **assumes** the same per-run
request rate on every route and linear scaling: 180 to 600 RPM at 100 and
1,800 to 6,000 RPM at 1,000. That is an extrapolation, not a measurement,
and Codex traffic does not pass through Envoy.

| Route | N | Required (counted) | Required RPM (assumed) | Sourced default | Rate verdict | Spend (2.2) |
|---|---|---|---|---|---|---|
| Anthropic API, Sonnet 5.5 | 100 | ITPM 0.22M to 3.44M; OTPM 0.05M to 0.86M | 180 to 600 | Scale: 10,000 RPM, 10M ITPM, 2M OTPM | fits Scale across the range | within $200k/month at the low end; above it at the high end |
| Anthropic API, Sonnet 5.5 | 1,000 | ITPM 2.15M to 34.4M; OTPM 0.54M to 8.60M | 1,800 to 6,000 | Scale, as above | low end fits Scale; high end exceeds ITPM and OTPM: Custom tier or a requested increase | within the cap only at the low end and 8 h/day |
| Anthropic API, Opus 5.5 | 100 | ITPM 0.11M to 1.72M; OTPM 0.03M to 0.43M | 180 to 600 | Scale: 10,000 / 10M / 2M | fits Scale across the range | as Sonnet at 100 |
| Anthropic API, Opus 5.5 | 1,000 | ITPM 1.08M to 17.2M; OTPM 0.27M to 4.30M | 1,800 to 6,000 | Scale, as above | low end fits; high end exceeds ITPM and OTPM | as Sonnet at 1,000 |
| Bedrock, Sonnet 5.5 | 100 | all tokens 2.69M to 43.0M; excluding cache reads 0.27M to 4.30M | 180 to 600 | 6,000,000 cross-region TPM per Region, adjustable; RPM **UNVERIFIED** | excluding cache reads: fits; all tokens: low end fits, high end needs an increase ("aren't granted automatically") | **UNVERIFIED** (prices not extracted) |
| Bedrock, Sonnet 5.5 | 1,000 | all tokens 26.9M to 430M; excluding cache reads 2.69M to 43.0M | 1,800 to 6,000 | as above | all tokens: exceeds across the range; excluding cache reads: low end fits, high end exceeds | **UNVERIFIED** |
| Bedrock, Opus 5.5 | 100 | all tokens 1.34M to 21.5M; excluding cache reads 0.13M to 2.15M | 180 to 600 | 30,000,000 cross-region TPM per Region, adjustable; on-demand 15,000,000, not adjustable; RPM **UNVERIFIED** | fits cross-region either way; on-demand: high end exceeds if cache reads count | **UNVERIFIED** |
| Bedrock, Opus 5.5 | 1,000 | all tokens 13.4M to 215M; excluding cache reads 1.34M to 21.5M | 1,800 to 6,000 | as above | excluding cache reads: fits cross-region; all tokens: low end fits, high end exceeds | **UNVERIFIED** |
| Vertex, Sonnet 5.5 or Opus 5.5 | 100 | as the Bedrock rows | 180 to 600 | **UNVERIFIED** | **UNVERIFIED** | as Anthropic API, or up to 10% more (1.6) |
| Vertex, Sonnet 5.5 or Opus 5.5 | 1,000 | as the Bedrock rows | 1,800 to 6,000 | **UNVERIFIED** | **UNVERIFIED** | as above |
| OpenAI API, GPT-6.1-Sol | 100 | all tokens 2.69M to 43.0M; excluding cached input 0.27M to 4.30M | 180 to 600 | Grow: 15,000 RPM, 40,000,000 TPM (Launch 10,000 / 4,000,000) | RPM fits; excluding cached input: fits Grow; all tokens: low end fits, high end (43.0M) exceeds 40M | within $200k/month at the low end; above it at the high end; beyond Grow **UNVERIFIED** |
| OpenAI API, GPT-6.1-Sol | 1,000 | all tokens 26.9M to 430M; excluding cached input 2.69M to 43.0M | 1,800 to 6,000 | Grow, as above | RPM fits Grow; tokens: low end fits under either reading, high end exceeds under either | within the cap only at the low end and 8 h/day |

Tier advancement and approvals: Anthropic organizations "are placed on a
tier automatically based on usage history and account standing", and higher
limits are requested with "Request tier increase" (1.6). OpenAI tiers
upgrade "automatically as its total credit purchases reach each threshold"
(1.6). Bedrock "Quota increases aren't granted automatically." Vertex's
process: **UNVERIFIED**. Burst behaviour ("Short bursts of requests can
exceed the limit and trigger rate limit errors", Anthropic rate-limits page)
and increase lead times are **UNVERIFIED** in practice.

**Platform limits that no provider purchase fixes:**

- The shared Envoy local rate limit is one bucket of `max_tokens: 100`,
  `tokens_per_fill: 10`, `fill_interval: 1s`
  (`docker/sidecar-proxy/envoy.yaml:155-158`), so 10 requests per second
  sustained, flagged as possibly saturating at 100 (`docs/north-star.md:167`,
  #1720).
- There is no multi-host executor; 1,000 is out of reach "by construction"
  (`docs/north-star.md:181`, #1734).
- Every credential is inside the sandbox today (`docs/north-star.md:182`),
  which gates any remote executor tier (#1735, #724).

## 3. Design: a credential as a placement input

**Exists today:** one `SecretStr` per credential
(`packages/syn-shared/src/syn_shared/settings/config.py:253`, `:263`,
`:273`); no pool, no record of which credential served an attempt, no
quota-aware admission. A Claude quota hit reads as `UNKNOWN` because
`_CLAUDE_QUOTA_PHRASES` is empty
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/upstream_failure.py:84`, #1669).
Everything below is **proposed**; none of it exists. Whether a pool is worth
building at all depends on section 1: a pool of API keys in one organization
shares one quota scope and buys no capacity, so the main value of this
design under the compliant routes is attribution, admission and fail-fast
on quota, plus pooling across separately contracted organizations or
regions if the owner arranges them.

### 3.1 Names and identities

"Account" in the brief bundles three things that are not always the same;
merging them double-counts capacity.

- **Model credential** (`model_credential_id`): what is injected into one
  attempt. An opaque, operator-assigned label, validated against a fixed
  pattern (lowercase letters, digits and hyphens, bounded length), never the
  secret. Fields: provider, plan, credential reference (a resolver key, never
  the value, e.g. `<credential-ref>`).
- **Quota scope** (`quota_scope_id`): what the provider counts limits
  against. A subscription seat is one scope. Several Anthropic API keys in one
  organization share one scope ("Limits are set at the organization level",
  section 1.6); OpenAI scopes are organization and project. Windows belong to
  the scope.
- **Billing owner:** who pays and whose terms apply, recorded so the
  compliance route is visible in configuration.

The code term is not "account". That word already means the operator-facing
sentence in this code: `account()` in
`packages/syn-shared/src/syn_shared/upstream_failure.py:65` and `:90`,
`FailureAccount` at
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/errors.py:481`
and `failure_account()` at `:573`, with general usage in
`docs/architecture/orchestration-ubiquitous-language.md:181`. "Provider
account" is used here only in prose. The vocabulary edits belong to issue 1.

### 3.2 Two lanes

- "Invocation X ran under credential C" is a domain fact: it survives
  restart and drives attribution. Recorded at invocation registration (3.4).
- Quota window readings are Lane 2 telemetry and never go on the event stream.
- Reservations and availability (3.3) are infrastructure state in Postgres,
  like `execution_budget`. Per ADR-060 they fail fast without Postgres, and
  any test double inherits `InMemoryAdapter`.

### 3.3 Placement is a per-attempt reservation, not part of the executor claim

The provider is decided per phase and can switch on fallback, so the ADR-072
D3 run claim
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:148-179`)
cannot know the credential, and a whole-run lock would idle credentials the
run is not using. Proposed, to be ratified by an ADR amending ADR-072:

- `quota_window` rows, one per (quota scope, window kind, model scope): unit
  (percent of window for subscriptions; tokens or requests per minute for API
  scopes), `observed_remaining`, `observed_at`, `resets_at`, `exhausted_until`,
  and a concurrency `capacity` on the scope.
- `credential_reservation` rows, one per attempt: holder = the attempt's
  `attempt_id`, the executor run claim it belongs to, `model_credential_id`,
  estimated demand per window in that window's unit, `reserved_at`, and a
  `lease_token`.
- **Claim, one transaction:** lock every applicable window row of the
  candidate scope `FOR UPDATE`; check concurrency (reservations < capacity),
  `exhausted_until` null or past, observation freshness, and for every window
  `observed_remaining - sum(demand of reservations reserved after observed_at)
  >= this attempt's demand`; insert the reservation. Capacity check and claim
  together, as ADR-072 D3 requires. A check outside this transaction is not
  a reservation and is not relied on.
- **Renew** only under the matching `attempt_id` and `lease_token`, in the
  shape of `PostgresCaptureDeliveryJobs.renew`
  (`packages/syn-adapters/src/syn_adapters/session_inventory/capture_delivery_jobs.py:102-120`).
- **Release** is idempotent: delete by (`attempt_id`, `lease_token`); a
  duplicate or stale-token release changes nothing.
- **Executor death:** a reservation is not freed by expiry alone, because the
  agent may still be spending. It is released by the reaper that releases the
  executor's charge, after ADR-072's fencing confirms the run is gone
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:181-182`).
  ADR-072 D2/D3 are accepted but not built.

**What this is and is not.** Subscription windows are reported as a
percentage with no per-request attribution, so reservation demand is an
estimate (p90 of past attempts for that phase and model once #1716/#1718
measure it; a configured default until then). This is a **probabilistic
admission policy, not a guarantee** that a window covers an attempt.

**Reconciliation.** A new observation supersedes reservations made before
its `observed_at`; reservations made after it still count against it. A
finished attempt releases its reservation; actual use appears in the next
observation.

**Unknown or stale signals:** an owner decision. Recommended default: admit
under the concurrency cap only and record the attempt as admitted unguarded.
The alternative, refuse until fresh, is safer for quota and worse for
availability.

### 3.4 Attribution binds the credential before launch, per attempt

**Exists today:** a durable invocation record precedes every dispatch,
retries included
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/SessionLifecycleManager.py:203-221`),
and dispatch is refused without it
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/invocation_attempt.py:28-35`).
The completion event records only `agent_provider` and `agent_model`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/AgentExecutionCompletedEvent.py:50-72`).

**Proposed:** add `model_credential_id` to `SessionInvocationState`
(`packages/syn-domain/src/syn_domain/contexts/agent_sessions/_shared/session_invocation.py:22-27`)
and `SessionInvocationRecordedEvent`
(`packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/events/SessionInvocationRecordedEvent.py:9-17`),
passed by orchestration at `prepare_invocation`, carried through the outcome
update (which rebuilds the state field by field and would otherwise drop it:
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/SessionLifecycleManager.py:238-246`),
and non-rebindable like `attempt_id` and `harness`
(`packages/syn-domain/src/syn_domain/contexts/agent_sessions/_shared/session_invocation.py:83-85`).
An attempt that crashed before completion still names its credential.
Orchestration owns what a credential is and chooses it; agent_sessions
records only the opaque id, as it already records `harness`.

### 3.5 Selection rule

Eligibility is the reservation predicate in 3.3. Among eligible credentials:

- For a window that **resets in full at a known time** (5-hour, weekly),
  prefer the soonest reset: headroom is lost at reset.
- For **rolling** windows (API token buckets, "continuously replenished",
  section 1.6), reset time means nothing; prefer the lowest reserved fraction.
- Tie-break: lowest reserved fraction, then a stable order on
  `model_credential_id`.

### 3.6 No eligible credential

At a run's first phase the run should not be claimed: extend ADR-072's
`defer`/`retry_at` to fresh starts, with `retry_at` the earliest
`exhausted_until`. Mid-run, ADR-072 has no defer
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:412`
covers resumes only). That gap is left to the owner.

### 3.7 A limit hit during a phase: two separate cases

**Exists today:** fallback fires on CAPACITY or QUOTA to a different provider
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/busy_upstream.py:83-85`),
and neither fallback nor retry runs after an attempt that did work
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/busy_upstream.py:269`,
`:280`; witness at
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/agent_attempts.py:151`;
reason at
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/agent_attempts.py:22-28`).

**(a) Pre-work failover (proposed).** Only when the activity witness says
nothing was done. Order: same provider on another credential, then the
declared cross-provider `fallback_agent`. It draws from the same phase
deadline and cost limit
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/agent_attempts.py:190`,
`:195`). The failed scope's window gets `exhausted_until = resets_at`, or a
configured conservative window when no reset is stated.

This needs new work: a **late credential-staging seam**. Codex auth is a file
staged once at setup, and the code says there is no later staging point
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:158-169`;
install at
`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:731-751`).
Replacement must confirm the previous agent process exited, remove the old
credential, write the new one, then dispatch. A workspace never holds two
credentials of the same provider at once. For Claude, the credential is in
the agent env passed to each dispatch
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/agent_attempts.py:366-372`),
so a per-attempt env swap looks feasible (inferred, to verify in the
handler).

**(b) Continuation after partial work: not supported, and a pool does not
recover it.** Rerunning the prompt would redo edits, commands or pushes over
a changed tree. **Today**, a partial-work failure is not rerun, and how it
is classified depends on the provider: a Codex quota message that matches
`_CODEX_QUOTA_PHRASES` is classified QUOTA, with a reset time only when the
message names a parseable date (`_codex_quota_reset` returns `None`
otherwise); a Claude quota failure reads as UNKNOWN, with no reset, because
`_CLAUDE_QUOTA_PHRASES` is empty and its reset reader is `_no_reset`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/upstream_failure.py:74-106`,
`:139-153`; #1669). **Proposed:** once #1669 lands, a partial-work quota
failure on either provider fails as QUOTA with its reset time when the
provider supplies one, and the pool still does not rerun it. A future
continuation needs: (1) the native session or transcript, and whether
it can resume under a different credential (**UNVERIFIED** for both
harnesses); (2) the working tree including uncommitted files; (3) a durable
successor attempt identity linked to its predecessor; (4) the external
actions already completed (pushes, PR comments, issues), so they are not
repeated; (5) the remaining phase deadline and cost budget. This is why
admission (3.3) matters most: its job is to make mid-work exhaustion rare.

### 3.8 Live signals behind a port

Define a `QuotaSignalSource` Protocol here. Adapters: Envoy response headers
on the Claude path (`docker/sidecar-proxy/envoy.yaml:52-64`), conditional on
Anthropic returning `anthropic-ratelimit-*` headers on subscription traffic
(**UNVERIFIED**); a polled usage source (codexbar or a provider usage
endpoint); and the CLI quota line. CLI text parsing belongs in
agentic-workspace (#1605), per the harness boundary rule. Codex traffic does
not pass through Envoy (no OpenAI host in `docker/sidecar-proxy/envoy.yaml`),
so Codex quota can come only from CLI output or a usage query.

### 3.9 Secrets

**Exists today:** every credential is inside the sandbox
(`docs/north-star.md:182`), and a workspace can already hold two: delegation
stages both
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:140-155`),
and a codex fallback stages Codex auth for the whole phase (`:158-169`).

- Direct injection is an **interim, single-tenant** design, acceptable only
  under ADR-024's stated posture
  (`docs/adrs/ADR-024-setup-phase-secrets.md:511-515`).
- ADR-070's map covers db, redis, minio and the GitHub App key, not model
  credentials (`docs/adrs/ADR-070-credential-rotation.md:101-108`). Proposed:
  a `ModelCredentialResolver` contract (credential reference in, secret out,
  resolved at setup from a file in the ADR-070 D1 style, never from an env
  var). `ServiceCredentialConfig`
  (`packages/syn-shared/src/syn_shared/settings/credentials.py:30-50`) stays
  injection metadata.
- Target: proxy-side injection keyed by workspace and credential
  (`packages/syn-shared/src/syn_shared/settings/credentials.py:7-8`, "Phase 2"),
  via #724 for the Claude API key and #1735 overall. #724 does not solve
  Codex (`docs/north-star.md:182`). Codex route: unresolved. Acceptance
  evidence for it: a Codex phase runs while a scan of the workspace's
  filesystem and environment finds no access or refresh token, and Codex
  traffic leaves through a platform-owned component.
- Whether OAuth may be proxied at all: the Claude Code page says developers
  "may not collect, store, or intermediate Claude.ai credentials or session
  tokens" (section 1.2). Read plainly, that weighs against a proxy that holds
  a subscription token; it does not affect API keys, which "This does not
  restrict".

### 3.10 Codex refresh-token risk (UNVERIFIED)

The same `auth.json` is copied into every concurrent workspace. If refresh
tokens rotate on use, parallel copies could invalidate each other. OpenAI's
CI/CD auth page (1.3) states the operational rule without saying why: "Do
not share the same file across concurrent jobs or multiple machines". The
mechanism stays unverified. The
settling test: read agentic-workspace's codex adapter, then run two
workspaces on one blob past a refresh. One blob per credential narrows the
risk; it does not remove it.

## 4. Issues to file (bodies for the owner; not filed by this PR)

Smallest useful slice first. #1718 ("per-provider concurrency budgets and
quota-per-run telemetry") already covers per-provider budgets and quota
telemetry; issues 3 and 5 below should be filed as its subtasks rather than
as siblings. Existing fallback tests (for example
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_pc83_a_phase_falls_back_once.py`)
assert provider, model and call counts, not credentials, and stay green
without a pool, so each issue names tests that exercise the new behaviour.

1. **Record which model credential each invocation ran under.**
   `model_credential_id` on `SessionInvocationState` and
   `SessionInvocationRecordedEvent` (optional, default `None` for replay of
   historical events; check the ESP event-versioning rule for whether that
   needs `v2`), set at `prepare_invocation`, preserved by `finish_invocation`,
   non-rebindable, through the read model and API type to the CLI via
   `just codegen`. Label validated at settings load. Vocabulary: "model
   credential" in the orchestration and agent_sessions files; "account"
   listed as not used for this concept. **Tests:** a retry produces two
   invocations each naming its credential (a double supplies ids A and B),
   recovered after a restart; an invocation that crashed after registration
   still names its credential; a label failing the pattern is refused at
   load; serialized events and logs, produced with synthetic secret values
   configured, contain none of them.
2. **Several credentials per provider in settings, with quota scope and
   billing owner** (ADR-004, ADR-070 extension). A list of credentials:
   label, provider, plan, credential reference, quota scope, billing owner,
   concurrency cap; a `ModelCredentialResolver`; first-eligible selection by
   concurrency; startup seeds scope and window rows, and a credential or scope
   present in only one place fails startup. **Tests:** two Codex credentials
   configured, each workspace holds exactly one Codex auth file matching its
   recorded `model_credential_id`; two credentials sharing a scope count
   against one cap.
3. **Quota-aware reservations for Codex, with an ADR amending ADR-072**
   (subtask of #1718). The `quota_window` and `credential_reservation` tables
   and the claim, renew, release and reap rules of 3.3; `exhausted_until` from
   `QuotaExhaustion.resets_at`; the unknown-signal policy. Codex first because
   its quota line and reset are already parsed
   (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/upstream_failure.py:67-106`).
   Depends on ADR-072 D2/D3. **Tests:** N simultaneous claimers against
   headroom for k < N, exactly k succeed; two holders renew independently; a
   duplicate release changes nothing; a stale-token release is refused; a
   dead executor's reservations are not freed by expiry while fencing is
   unresolved and are freed once reaped; a QUOTA failure on scope A blocks A
   until reset and the next claim lands on B; a stale observation follows the
   configured policy.
4. **Pre-work failover to another credential of the same provider, before
   `fallback_agent`.** Includes the late credential-staging seam and the
   one-credential-per-provider-per-workspace rule. **Tests:** an attempt that
   did work is never failed over; after failover the old Codex auth file is
   gone and the new one present; failover draws from the phase's existing
   deadline and cost limit.
5. **The `QuotaSignalSource` port** (subtask of #1718), with a polled
   usage-source adapter first and the Envoy header adapter for Claude once
   header presence on the chosen route is confirmed. Readings are Lane 2
   telemetry joined to `model_credential_id`; this produces the per-seat
   measurement section 2.4 lacks.
6. **Design: continuation after partial work on another credential.** The
   five-part contract in 3.7(b), starting with whether either harness can
   resume a session under a different credential.
7. **Proxy-side injection per credential, and a Codex route**, as a
   dependency note on #724 and #1735, adding the Codex acceptance evidence in
   3.9.

Referenced, not refiled: #1669 (Claude quota line, needed before Claude gets
issue 3), #1716 (per-phase usage), #1720 (Envoy bucket), #1605 (harness
parsing to agentic-workspace).

## 5. Decisions for the owner

1. **Compliance route** (#1612 "provider account ownership"): Anthropic API
   key under the Commercial Terms, usage-based Enterprise, Bedrock or Vertex,
   or an explicit arrangement via Anthropic sales; for OpenAI, an API key or
   (once its terms are quoted) Enterprise with flexible pricing. This document
   informs the choice; it does not make it.
2. **Today's single OAuth token:** section 1.5 finds it not established as
   permitted. Whether to keep it while the route is chosen, and whether to ask
   Anthropic sales, is the owner's call.
3. **Mid-run behaviour when no credential is eligible:** hold the executor
   slot up to a bound, or amend ADR-072 to defer mid-run.
4. **Unknown-signal policy:** admit under the concurrency cap and record
   "unguarded" (recommended), or refuse until a fresh reading.
5. **Who files issues 1 to 7**, and confirmation that 3 and 5 go under #1718.
6. **Spend ceiling:** $75 to $1,200 per hour at 100, $750 to $12,000 at 1,000
   (estimates), against the $200,000 monthly cap of Anthropic's Scale tier and
   OpenAI's Grow tier.

## Verification notes

- The OpenAI Terms of Use quotes come from an Internet Archive capture
  dated 2026-10-08, not the live page (403 to curl); a reviewer with a
  browser should re-open the live page. The Service and Business Terms are
  still the gap.
- Bedrock Claude prices, Vertex Claude quotas, Bedrock request quotas and
  OpenAI's cached-input counting are **UNVERIFIED** and appear in 2.5 and
  2.6 only as such.
- Each section 1 quote was copied from the fetched page text on 2026-10-08;
  one quote per provider should be re-opened at its URL by the reviewer.
- Each arithmetic row was computed from the inputs stated beside it.
