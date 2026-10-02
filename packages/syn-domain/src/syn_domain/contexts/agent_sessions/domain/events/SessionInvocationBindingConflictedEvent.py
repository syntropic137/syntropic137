"""A native identity claim that contradicts an invocation's existing binding.

Recorded instead of rebinding: the invocation keeps its first native identity,
and this claim becomes host evidence the resolver reports as a conflicting
binding. Primitive wire fields keep historical replay portable.
"""

from event_sourcing import DomainEvent, event


@event("SessionInvocationBindingConflicted", "v1")
class SessionInvocationBindingConflictedEvent(DomainEvent):
    session_id: str
    execution_id: str
    phase_id: str
    invocation_id: str
    attempt_id: str
    harness: str
    #: The identity the invocation stays bound to.
    bound_native_session_id: str
    #: The contradicting identity that was reported and NOT bound.
    conflicting_native_session_id: str
