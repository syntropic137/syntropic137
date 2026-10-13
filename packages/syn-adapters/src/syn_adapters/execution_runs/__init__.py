"""Run Queue adapters for the ``ExecutionRunQueue`` port (ADR-072).

Production uses ``PostgresExecutionRunQueue`` only. The in-memory double is
imported from ``syn_adapters.execution_runs.memory`` by tests and refuses to
construct outside test/offline (ADR-060).
"""

from syn_adapters.execution_runs.postgres import PostgresExecutionRunQueue

__all__ = ["PostgresExecutionRunQueue"]
