"""Costs context - Session and execution cost tracking.

This context handles real-time cost tracking with session-level granularity
that aggregates up to execution-level. Sessions are the atomic unit
(single agent, single phase, single workspace/sandbox).
"""
