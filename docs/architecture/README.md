# AEF Architecture Documentation

**Last Updated:** 2026-02-03

---

## 📐 High-Level Architecture

![AEF VSA Overview](./vsa-overview.svg)

### VSA Overview Diagram

**🤖 Auto-generated** - This diagram is generated from the VSA manifest.

**Shows:**
- 4 Bounded Contexts with 6 Aggregates total
- **Orchestration** (3 aggregates): Workflow, Workspace, WorkflowExecution
- **Agent Sessions** (1 aggregate): AgentSession
- **GitHub** (1 aggregate): Installation
- **Artifacts** (1 aggregate): Artifact
- Infrastructure Layer (TimescaleDB, EventStore, Redis, MinIO)

**Regenerate:**
```bash
just diagram  # Updates docs/architecture/vsa-overview.svg
```

**Update frequency:** After domain model changes (new contexts, commands, events)

---

## 📚 Detailed Architecture (Phase 2)

### 🤖 Auto-Generated Diagrams

**These are generated from code/data - do NOT edit manually:**

| Diagram | Description | Generate With | Update When |
|---------|-------------|---------------|-------------|
| [Projection Subscriptions](./projection-subscriptions.md) | Event → Projection mappings | `claude generate-architecture-docs` | After projection changes |
| [Event Flow Summary](./event-flows/README.md) | Top event flows table | `claude generate-architecture-docs` | After event changes |

**To regenerate all auto-generated diagrams:**

```bash
# 1. Update manifest
vsa manifest --config vsa.yaml --output .topology/aef-manifest.json --include-domain

# 2. Regenerate diagrams
claude generate-architecture-docs
```

---

### 📝 Manual Architecture Documentation

**These are educational/design docs - edit as needed:**

#### Core Concepts

- **[Event Architecture](./event-architecture.md)** 📝 Manual
  - **What:** Domain Events vs Observability Events pattern
  - **Why:** Explains the two-pattern system (ADR-018)
  - **When to update:** Rarely (stable architectural pattern)
  - **Reference:** [ADR-018](../adrs/ADR-018-commands-vs-observations-event-architecture.md)

#### Real-time Communication

- **[Real-time Communication](./realtime-communication.md)** 📝 Manual
  - **What:** WebSocket control plane + SSE streaming
  - **Why:** How Dashboard gets real-time updates
  - **When to update:** When control flow changes
  - **Reference:** [ADR-019](../adrs/ADR-019-websocket-control-plane.md)

#### Infrastructure & Deployment

- **[Docker Workspace Lifecycle](./docker-workspace-lifecycle.md)** 📝 Manual
  - **What:** Setup phase → Agent phase with secret clearing
  - **Why:** Security model for agent execution
  - **When to update:** When workspace lifecycle changes
  - **Reference:** [ADR-024](../adrs/ADR-024-setup-phase-secrets.md)

- **[Infrastructure Data Flow](./infrastructure-data-flow.md)** 📝 Manual
  - **What:** How data flows through EventStore, TimescaleDB, Redis, MinIO
  - **Why:** Understanding service integration
  - **When to update:** When adding/removing infrastructure
  - **References:** Multiple ADRs

#### Detailed Flows

- **[Event Flows](./event-flows/)** 📝 Manual (detailed sequence diagrams)
  - Workflow creation flow
  - Execution start flow
  - Token consumption flow

---

## 🏗️ Architecture Principles

AEF follows these architectural patterns:

| Pattern | Description | Key ADRs |
|---------|-------------|----------|
| **Vertical Slice Architecture** | Feature-first organization | [ADR-019](../adrs/ADR-019-vsa-standard-structure.md) |
| **CQRS** | Command/Query separation with projections | [ADR-008](../adrs/ADR-008-vsa-projection-architecture.md) |
| **Event Sourcing** | Domain events as source of truth | [ADR-007](../adrs/ADR-007-event-store-integration.md) |
| **Hexagonal Architecture** | Ports & Adapters for clean boundaries | [ADR-019](../adrs/ADR-019-websocket-control-plane.md) |
| **Two Event Patterns** | Domain (ES) vs Observability (Log) | [ADR-018](../adrs/ADR-018-commands-vs-observations-event-architecture.md) |

---

## 🔄 Generation Strategy

### Auto-Generated Content (Single Source of Truth)

**Source:** VSA manifest (`.topology/aef-manifest.json`)

**Contains:**
- Commands, Events, Projections (names, counts)
- Event-to-Projection relationships
- Projection-to-ReadModel mappings
- Bounded context structure

**Generation Pipeline:**

```
VSA Scanner → Manifest JSON → Diagram Generator → Markdown + Mermaid
    ↓              ↓                  ↓                    ↓
  Code     .topology/aef-    Python script      docs/architecture/
           manifest.json                     projection-subscriptions.md
```

**Regeneration:**
- **Automatic:** Before each release (CI/CD)
- **Manual:** After domain changes (`claude generate-architecture-docs`)

### Manual Content (Design Documentation)

**Source:** Human understanding of architecture

**Purpose:**
- Explain "why" not just "what"
- Show patterns and principles
- Aid developer onboarding
- Document design decisions

**Maintenance:**
- Update when architecture changes (like ADRs)
- Review during major refactorings
- Keep close to implementation

---

## 🎯 Quick Reference

**Need to understand...**

| ...what? | See this |
|----------|----------|
| Overall system structure | [ARCHITECTURE.svg](../ARCHITECTURE.svg) |
| Why we have two event types | [Event Architecture](./event-architecture.md) |
| How Dashboard gets real-time updates | [Real-time Communication](./realtime-communication.md) |
| How agent execution is secured | [Docker Workspace Lifecycle](./docker-workspace-lifecycle.md) |
| Which events trigger which projections | [Projection Subscriptions](./projection-subscriptions.md) |
| How services connect | [Infrastructure Data Flow](./infrastructure-data-flow.md) |
| Specific event flow details | [Event Flows](./event-flows/) |

---

## 📖 Related Documentation

- **[ADRs](../adrs/)** - Architecture Decision Records
- **[AGENTS.md](../../AGENTS.md)** - System overview for AI agents
- **[VSA Documentation](../../lib/event-sourcing-platform/vsa/README.md)** - VSA standard details

---

## 🤝 Contributing

### Updating Auto-Generated Diagrams

**DO:**
- ✅ Run `claude generate-architecture-docs` after manifest changes
- ✅ Commit the generated files
- ✅ Ensure manifest is up-to-date first

**DON'T:**
- ❌ Edit auto-generated files manually (changes will be lost)
- ❌ Commit out-of-date diagrams

### Updating Manual Documentation

**DO:**
- ✅ Edit markdown files directly
- ✅ Update when architecture changes
- ✅ Keep diagrams accurate to implementation
- ✅ Reference relevant ADRs

**DON'T:**
- ❌ Let documentation drift from reality
- ❌ Remove explanatory text (it's valuable!)

---

## 🔮 Future Enhancements (Phase 3)

**Planned:**
- Event Modeling standard support (EventModeling.org)
- Interactive timeline-based visualizations
- Swimlane diagrams for multi-actor flows
- C4 model integration
- PlantUML export

**See:** [Project Plan Phase 3](../../PROJECT-PLAN_20260126_PHASE3-EVENT-MODELING.md) (when created)

---

**Questions?** See [AGENTS.md](../../AGENTS.md) or relevant ADRs.
