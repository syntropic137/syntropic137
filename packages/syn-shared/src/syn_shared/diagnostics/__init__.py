"""Evidence gathered about a failure, at the moment it is still gatherable."""

from syn_shared.diagnostics.signal_death import (
    SignalDeath,
    name_exit_status,
    signal_number_of,
)

__all__ = ["SignalDeath", "name_exit_status", "signal_number_of"]
