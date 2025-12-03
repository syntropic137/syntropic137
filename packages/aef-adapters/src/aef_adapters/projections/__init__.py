"""Projection management for CQRS read models."""

from .manager import ProjectionManager, get_projection_manager

__all__ = [
    "ProjectionManager",
    "get_projection_manager",
]
