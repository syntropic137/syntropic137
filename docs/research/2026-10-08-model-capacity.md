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
- The OpenAI Terms of Use, Service Terms and Business Terms all returned
  HTTP 403 to every fetch attempt, so **every OpenAI terms question is
  UNVERIFIED** here. The one OpenAI statement fetched is that an API key is
  "Great for automation in shared environments like CI" (section 1.3).
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
2026-10-08"). Quotes are verbatim and in block quotes. Where a quoted
sentence contains an em dash on the source page, the quote stops before it
and the cut is marked `[...]`. Typographic apostrophes and quotation
marks are rendered as ASCII; nothing else inside a quote is changed.
Anything not fetched is marked **UNVERIFIED** and kept out of section 2's
arithmetic.

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
| OpenAI Terms of Use | https://openai.com/policies/terms-of-use/ (also `/row-terms-of-use/`, `/en-GB/policies/terms-of-use/`) | **403, UNVERIFIED** |
| OpenAI Service Terms | https://openai.com/policies/service-terms/ | **403, UNVERIFIED** |
| OpenAI Business Terms | https://openai.com/policies/business-terms/ | **403, UNVERIFIED** |
| Using Codex with your ChatGPT plan | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan | **403, UNVERIFIED** |
| Codex pricing and plan limits | https://developers.openai.com/codex/pricing | 200 |
| OpenAI API rate limits | https://platform.openai.com/docs/guides/rate-limits | 200 |

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

**Same page**, "Authentication and credential use" (the first two paragraphs in full; the third sentence of the second paragraph is cut at an em dash on the source page):

> Claude Code authenticates with Anthropic's servers using OAuth tokens or API keys. These authentication methods serve different purposes:
> OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications.

> Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens [...]

**Same page**, the paragraph that follows it:

> This does not restrict how customers provision and manage their own API keys or third-party inference provider credentials [...] provided the resulting usage is billed to the key owner under their agreement with Anthropic (or the applicable provider) and is not resold or intermediated as described above. Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code as described under Can customers offer Claude Code in their products? above.
>
> Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice.
>
> For questions about permitted authentication methods for your use case, please contact sales.

**Same page**, "Can customers offer Claude Code in their products?" (first sentence and second bullet):

> Unless we've mutually agreed otherwise, preinstalling or running Claude Code in your products or services (e.g. in hosted sandboxes or other agent infrastructure) requires agreeing to our Commercial Terms of Service and complying with the conditions below:

> Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf. Each end user must authenticate with their own Anthropic API key, Claude subscription plan credentials, or 3P inference provider credential (Amazon Bedrock, Google Cloud's Agent Platform, Microsoft Foundry). That usage is billed directly to the end user under their own agreement with Anthropic or, for third-party inference providers, with the applicable provider.

**Same page**, "Commercial agreements":

> Whether you're using the Claude API directly (1P) or accessing it through Amazon Bedrock or Google Cloud's Agent Platform (3P), your existing commercial agreement will apply to Claude Code usage, unless we've mutually agreed otherwise.

**Usage Policy**, under "Do Not Abuse Our Platform" (https://www.anthropic.com/legal/aup, accessed 2026-10-08; the page header reads "Effective November 12, 2026"):

> Coordinate malicious activity across multiple accounts, or create multiple accounts, to avoid detection, circumvent product guardrails, or generate identical or similar inputs that otherwise violate our Usage Policy

The Usage Policy does not say, in what was fetched, whether a usage limit is a "product guardrail". This document does not read it as covering usage limits; the anti-circumvention question for Anthropic rests on the Consumer Terms and Claude Code quotes above, not on this line.

**Commercial Terms**, D.4 (https://www.anthropic.com/legal/commercial-terms, accessed 2026-10-08):

> D.4. Use Restrictions. Customer may not and must not attempt to (a) access the Services to build a competing product or service, including to train competing AI models or resell the Services except as expressly approved by Anthropic; (b) reverse engineer or duplicate the Services; or (c) support any third party's attempt at any of the conduct restricted in this sentence.

No Commercial Terms clause on rate-limit circumvention or on automated access was found by searching the fetched text for "circumvent", "rate limit" and "usage limit".

### 1.3 OpenAI terms

**UNVERIFIED.** The Terms of Use, Service Terms, Business Terms and the
Codex-with-ChatGPT help article all returned 403 (section 1.1). The plan's
reviewer reported a 2026-10-08 spot-check that the Terms of Use prohibit
circumventing rate limits; this document could not re-quote it, so it is
**not** relied on. A reviewer with a browser should quote the account-sharing,
automated-access and rate-limit clauses here before any decision uses them.

The one OpenAI statement fetched on this topic, from the Codex pricing page
(https://developers.openai.com/codex/pricing, accessed 2026-10-08), next to
the "API Key" option:

> Great for automation in shared environments like CI.

That is a product description, not a terms clause, and it says nothing about
whether ChatGPT plan credentials may be used the same way.

### 1.4 Terms by usage pattern

Each cell is a pointer to a quote in 1.2 or 1.3, or **UNVERIFIED**. A cell
summarises which quote applies; the quote itself is the evidence.

| Pattern | Anthropic (Claude Code, Pro/Max) | Anthropic (Team / Enterprise seats) | Anthropic (API key, Bedrock, Vertex) | OpenAI (Codex, ChatGPT plans) | OpenAI (API key) |
|---|---|---|---|---|---|
| Supported CLI automation by its licensee | Consumer Terms automated-access clause: prohibited "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it". No fetched page explicitly permits headless subscription use. Claude Code page: limits "assume ordinary, individual usage". **Not established as permitted.** | Commercial Terms apply (License quote). No fetched clause addresses headless or automated seat use: **UNVERIFIED** | "Developers building products or services ... should use API key authentication through Claude Console or a supported cloud provider" | **UNVERIFIED** | "Great for automation in shared environments like CI" (product description, not terms) |
| One person's login used by a platform | "developers may not collect, store, or intermediate Claude.ai credentials or session tokens"; but "Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code". Whether copying one OAuth token into many automated workspaces is "signing in" is **not answered** by the quote. | Same Claude Code quotes; **UNVERIFIED** beyond them | "configuring an API key in a development environment, secrets manager, or machine image for use by the customer's own authorized users" is not restricted | **UNVERIFIED** | **UNVERIFIED** |
| Many personal subscriptions pooled | "You may not share your Account login information ... You also may not make your Account available to anyone else"; "Anthropic does not permit third-party developers ... to route requests through Free, Pro, or Max plan credentials on behalf of their users". **Likely outside the terms.** | Seats are per member (Team page: "This article applies to members of Team or Enterprise plan organizations"). Whether one automated service may route through many members' seats: **UNVERIFIED**. Team is not blanket permission. | n/a (organization-level) | **UNVERIFIED** | n/a |
| Per-user seat assignment | n/a | The Team page describes seats as assigned to members; no fetched clause permits non-human seat holders: **UNVERIFIED** | n/a | Business "$20/ user / month" (pricing page; per user). Terms: **UNVERIFIED** | n/a |
| Organization-level capacity | n/a | Usage-based Enterprise: quoted below the table | "Limits are set at the organization level." (rate-limits page) | Enterprise/Edu with flexible pricing: "no fixed rate limits. Usage scales with credits." (Codex pricing page) | "Rate limits are defined at the organization level and at the project level, not user level." (rate-limits guide) |
| Multi-account to exceed a limit | No clause found that names usage limits. Usage Policy "create multiple accounts, to ... circumvent product guardrails" is quoted, but whether a usage limit is a guardrail is **not stated**. The pooling quotes above apply regardless. | **UNVERIFIED** | Spend and rate limits are per organization (rate-limits page); creating extra organizations to evade them: **UNVERIFIED** | **UNVERIFIED** (reviewer's spot-check not re-quoted) | **UNVERIFIED** |

The usage-based Enterprise quote, cut at the em dash on the source page
(https://support.claude.com/en/articles/11845131-using-claude-code-with-your-team-or-enterprise-plan, accessed 2026-10-08):

> If your organization is on a usage-based Enterprise plan (including self-serve Enterprise), there are no per-seat usage limits [...] usage is based on consumption and billed at API rates.

### 1.5 What this means for today's single-token use

**Exists today.** The platform injects one Claude OAuth token into every
agent workspace
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:242-255`),
and the code's only stated basis is an unsourced note, "OAuth is out of scope
(ToS gray area for header proxying)"
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:251`;
`docs/adrs/ADR-024-setup-phase-secrets.md:531`).

**What the quotes establish.** The fetched pages do not explicitly permit
running one person's Pro or Max OAuth token in many concurrent automated
workspaces. The Consumer Terms prohibit automated access except via an API key
"or where we otherwise explicitly permit it", and the Claude Code page says
subscription limits "assume ordinary, individual usage". Whether the
platform's current use is covered by the "end user ... signing in to the
unmodified Claude Code binary with their own Claude subscription" sentence is
not answered by the text; the page's own answer is "please contact sales".
The owner should treat the current single-token posture as **unresolved, not
as permitted**, and the "gray area" note should be replaced with these quotes
(follow-up, not this PR).

**Compliant routes the quotes describe:** an Anthropic API key under the
Commercial Terms; Bedrock or Vertex under the existing commercial agreement;
a usage-based Enterprise plan billed at API rates; an explicit arrangement
with Anthropic sales. For OpenAI: an API key (organization or project limits).
Whether ChatGPT Enterprise with flexible pricing permits automated platform
use is **UNVERIFIED** (terms pages 403).

### 1.6 Limits and prices, sourced

Subscription windows (https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan, accessed 2026-10-08):

> Both Pro and Max plans have a five-hour session limit and a weekly limit. Max plans also have a separate weekly limit for Fable. These limits are shared across Claude and Claude Code, meaning all activity in both tools counts against the same limits.

No fetched page gives those windows as numbers. Max 5x versus 20x usage
amounts: **UNVERIFIED** (the Max usage article returned 404).

Codex plan limits (https://developers.openai.com/codex/pricing, accessed 2026-10-08):

> The estimates below show local messages per five-hour period for Plus and
> Standard Business. Pro plans currently have no five-hour limit.

> Local messages and cloud chats share your plan's usage allowance. Weekly
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
| GPT-6.1-Sol API | $2 input, $10 output, $0.10 cached, $2.50 cache write (repo convention) per MTok | **not re-fetched here**: taken from `packages/syn-shared/src/syn_shared/pricing/__init__.py:239-252`, which cites developers.openai.com, retrieved 2026-10-06 |

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

**Amazon Bedrock** (https://docs.aws.amazon.com/general/latest/gr/bedrock.html, accessed 2026-10-08): "Cross-region model inference tokens per minute for Anthropic Claude Opus 5.5", "Each supported Region: 30,000,000", adjustable "Yes"; the same for Sonnet 5.5 is "Each supported Region: 6,000,000", adjustable "Yes". The quota "considers the combined sum of input and output tokens". Whether cache reads count toward it: **UNVERIFIED**. From the user guide (https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html):

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

Per-model TPM/RPM for Codex models: **UNVERIFIED** (the page directs to the
organization's limits page).

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

All estimates. Against section 1.6: the Anthropic Scale tier's $200,000
monthly cap covers 100 at the low end of the range at either duty cycle, but
not the high end; 1,000 needs the Custom tier (or a cloud marketplace) at
any point in the range. OpenAI's Grow tier has the same $200,000 figure.

### 2.3 Tokens, by declared mix

No blended price without a mix. Each scenario assumes the same token mix,
chosen as an **assumption** for a long agentic run with heavy prompt caching:
90% cache read, 3% cache write, 5% uncached input, 2% output.

| Scenario | Prices used (per MTok) | Effective $/MTok = sum(share x price) | MTok per run at C = $3 / $12 |
|---|---|---|---|
| A. Sonnet 5.5 | 0.10 / 2.50 / 2 / 10 | 0.9x0.10 + 0.03x2.50 + 0.05x2 + 0.02x10 = 0.465 | 6.45 / 25.81 |
| B. Opus 5.5 | 0.20 / 5 / 4 / 20 | 0.18 + 0.15 + 0.20 + 0.40 = 0.93 | 3.23 / 12.90 |
| C. Codex, GPT-6.1-Sol | 0.10 / 2.50 / 2 / 10 | 0.465 (same rates as A) | 6.45 / 25.81 |

Tokens per minute = ($/h / 60) / effective $/MTok. Rate-limit-counted input
(Anthropic ITPM) = uncached input + cache write = 8% of the total; output
(OTPM) = 2%.

| Scenario | N | $/min | Total MTok/min | ITPM-counted MTok/min | OTPM MTok/min |
|---|---|---|---|---|---|
| A. Sonnet 5.5 | 100 | 1.25 to 20 | 2.69 to 43.0 | 0.22 to 3.44 | 0.05 to 0.86 |
| A. Sonnet 5.5 | 1,000 | 12.5 to 200 | 26.9 to 430 | 2.15 to 34.4 | 0.54 to 8.60 |
| B. Opus 5.5 | 100 | 1.25 to 20 | 1.34 to 21.5 | 0.11 to 1.72 | 0.03 to 0.43 |
| B. Opus 5.5 | 1,000 | 12.5 to 200 | 13.4 to 215 | 1.08 to 17.2 | 0.27 to 4.30 |
| C. GPT-6.1-Sol | 100 | 1.25 to 20 | 2.69 to 43.0 | n/a (OpenAI per-model limits UNVERIFIED) | n/a |
| C. GPT-6.1-Sol | 1,000 | 12.5 to 200 | 26.9 to 430 | n/a | n/a |

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
API keys versus usage-based Enterprise versus Bedrock or Vertex, all of
which are billed at or near API rates, so section 2.2 is the cost.

### 2.6 Feasibility, not just price

| Route | Need at 100 (scenario A, high end) | Sourced default | Verdict |
|---|---|---|---|
| Anthropic API, Sonnet 5.5 | ITPM 3.44M, OTPM 0.86M; spend up to $288k to $864k/month | Scale: 10M ITPM, 2M OTPM, $200k/month cap | Rate limits fit at Scale; spend cap does not at the high end: Custom tier |
| Anthropic API, Sonnet 5.5 at 1,000 | ITPM 34.4M, OTPM 8.6M | Scale: 10M / 2M | Exceeds Scale: Custom tier |
| Bedrock, Sonnet 5.5 | 43.0M tokens/min if cache reads count; 4.3M if they do not | 6,000,000 cross-region TPM per region, adjustable | Fits only if cache reads do not count (**UNVERIFIED**); increases "aren't granted automatically" |
| Bedrock, Opus 5.5 | 21.5M if cache reads count; 2.15M if not | 30,000,000 per region, adjustable | Fits at 100 either way; 1,000 (215M) needs an increase if cache reads count |
| Vertex | as above | **UNVERIFIED** | **UNVERIFIED** |
| OpenAI API | 43.0M total tokens/min at 100 | per-model TPM **UNVERIFIED**; Grow $200k/month | Spend cap binds at the high end; TPM unknown |

Requests per minute: the north star estimates 3 to 10 requests per second at
100 (`docs/north-star.md:167`), i.e. 180 to 600 RPM, within every tier's
1,000 RPM. Burst behaviour ("Short bursts of requests can exceed the limit
and trigger rate limit errors", rate-limits page) and increase lead times are
**UNVERIFIED** in practice.

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
a changed tree. The phase fails as QUOTA with its reset time, as today. A
future continuation needs: (1) the native session or transcript, and whether
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
tokens rotate on use, parallel copies could invalidate each other. The
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

- The OpenAI terms are the gap: a reviewer with a browser should quote the
  Terms of Use and Service Terms clauses on account sharing, automated access
  and rate-limit circumvention into section 1.3.
- Each section 1 quote was copied from the fetched page text on 2026-10-08;
  one quote per provider should be re-opened at its URL by the reviewer.
- Each arithmetic row was computed from the inputs stated beside it.
