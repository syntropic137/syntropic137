# ADR-003: Event Sourcing Decorator Patterns

## Status
Accepted

## Context
We are building an event-sourced system using the `event-sourcing-platform` Python SDK. The SDK provides several decorators for defining aggregates, commands, events, and their handlers. We need a consistent pattern for using these decorators across the codebase to ensure:

1. VSA CLI can discover and validate our domain structure
2. Consistent naming conventions
3. Clear separation between commands (intent) and events (facts)
4. Proper versioning for event schema evolution

## Decision

### Decorator Usage Pattern

We will use the following decorators from the `event-sourcing-platform` SDK:

#### 1. Class Decorators (for defining domain types)

| Decorator | Target | Purpose | Example |
|-----------|--------|---------|---------|
| `@aggregate(type)` | Aggregate class | Defines aggregate type name | `@aggregate("Workflow")` |
| `@command(type, desc?)` | Command class | Defines command type for VSA discovery | `@command("CreateWorkflow", "Creates a new workflow")` |
| `@event(type, version)` | Event class | Defines event type with schema version | `@event("WorkflowCreated", "v1")` |

#### 2. Method Decorators (for aggregate handlers)

| Decorator | Target | Purpose | Example |
|-----------|--------|---------|---------|
| `@command_handler(type)` | Aggregate method | Routes commands to handler | `@command_handler("CreateWorkflowCommand")` |
| `@event_sourcing_handler(type)` | Aggregate method | Routes events to state updater | `@event_sourcing_handler("WorkflowCreated")` |

### Naming Conventions

```
Command Class:     {Verb}{Noun}Command        → CreateWorkflowCommand
Command Type:      {Verb}{Noun}               → "CreateWorkflow"
Event Class:       {Noun}{PastVerb}Event      → WorkflowCreatedEvent
Event Type:        {Noun}{PastVerb}           → "WorkflowCreated"
Aggregate Class:   {Noun}Aggregate            → WorkflowAggregate
Aggregate Type:    {Noun}                     → "Workflow"
```

### Version Format

Events use simple versioning format for clarity:
- **Simple format (preferred)**: `"v1"`, `"v2"`, `"v3"`
- **Semver format (for complex migrations)**: `"1.0.0"`, `"2.1.0"`

Start all events at `"v1"`. Increment when schema changes require upcasters.

### Complete Example

```python
from event_sourcing import (
    AggregateRoot,
    DomainEvent,
    aggregate,
    command,
    command_handler,
    event,
    event_sourcing_handler,
)
from pydantic import BaseModel, ConfigDict


# === COMMAND (Intent - what we want to do) ===
@command("CreateWorkflow", "Creates a new workflow with phases")
class CreateWorkflowCommand(BaseModel):
    """Command to create a new workflow."""

    model_config = ConfigDict(frozen=True)

    aggregate_id: str | None = None  # Generated if not provided
    name: str
    # ... other fields


# === EVENT (Fact - what happened) ===
@event("WorkflowCreated", "v1")
class WorkflowCreatedEvent(DomainEvent):
    """Event emitted when a workflow is created."""

    workflow_id: str
    name: str
    # ... other fields


# === AGGREGATE (Consistency boundary) ===
@aggregate("Workflow")
class WorkflowAggregate(AggregateRoot["WorkflowCreatedEvent"]):
    """Workflow aggregate root."""

    def __init__(self) -> None:
        super().__init__()
        self._name: str | None = None

    # Command Handler - validates business rules, emits events
    @command_handler("CreateWorkflowCommand")
    def create_workflow(self, command: CreateWorkflowCommand) -> None:
        """Handle CreateWorkflowCommand."""
        if self.id is not None:
            raise ValueError("Workflow already exists")

        # Generate ID, emit event
        self._initialize(command.aggregate_id or str(uuid4()))
        self._apply(WorkflowCreatedEvent(
            workflow_id=self.id,
            name=command.name,
        ))

    # Event Handler - updates state only, NO business logic
    @event_sourcing_handler("WorkflowCreated")
    def on_workflow_created(self, event: WorkflowCreatedEvent) -> None:
        """Apply WorkflowCreatedEvent to state."""
        self._name = event.name
```

### VSA Slice Structure

Each vertical slice follows this file structure:

```
contexts/{context}/
├── _shared/
│   ├── {Noun}Aggregate.py      # @aggregate decorated
│   └── value_objects.py        # Shared value objects
└── {verb}_{noun}/              # snake_case slice folder
    ├── __init__.py
    ├── {Verb}{Noun}Command.py  # @command decorated
    ├── {Noun}{Verb}Event.py    # @event decorated
    ├── {Verb}{Noun}Handler.py  # Application service
    └── test_{verb}_{noun}.py   # Tests
```

### Metadata Access

Use helper functions to access decorator metadata:

```python
from event_sourcing import get_event_metadata, get_command_metadata

# Get event metadata
meta = get_event_metadata(WorkflowCreatedEvent)
print(meta.event_type)   # "WorkflowCreated"
print(meta.version)      # "v1"

# Get command metadata
meta = get_command_metadata(CreateWorkflowCommand)
print(meta.command_type)   # "CreateWorkflow"
print(meta.description)    # "Creates a new workflow with phases"
```

## Consequences

### Positive
- **Discoverability**: VSA CLI can scan codebase for decorated classes
- **Consistency**: Enforced naming conventions via decorators
- **Versioning**: Built-in event version tracking for schema evolution
- **Documentation**: Command descriptions serve as inline docs
- **Type Safety**: Decorators work with mypy strict mode

### Negative
- **Learning Curve**: Team must understand decorator patterns
- **Indirection**: Command routing is implicit via decorators

### Neutral
- **SDK Dependency**: Tied to event-sourcing-platform SDK patterns

## References
- [Event Sourcing Platform - Python SDK](../lib/event-sourcing-platform/event-sourcing/python)
- [ADR-010: Decorator Patterns (ES Platform)](../lib/event-sourcing-platform/docs/adrs/ADR-010-decorator-patterns.md)
- [VSA Concepts - Vertical Slices](../lib/event-sourcing-platform/docs-site/docs/vsa/concepts/vertical-slices.md)
