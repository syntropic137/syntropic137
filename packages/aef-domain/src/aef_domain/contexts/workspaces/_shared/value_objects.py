"""Value objects for workspace domain."""

from enum import Enum


class IsolationBackendType(str, Enum):
    """Isolation backend types matching aef-shared settings."""

    FIRECRACKER = "firecracker"
    KATA = "kata"
    GVISOR = "gvisor"
    DOCKER_HARDENED = "docker_hardened"
    CLOUD = "cloud"
    LOCAL = "local"  # For development only


class WorkspaceStatus(str, Enum):
    """Workspace lifecycle status."""

    CREATING = "creating"
    READY = "ready"
    RUNNING = "running"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    ERROR = "error"
