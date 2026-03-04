# Kata Containers Integration Path

> **Status**: Planned (Not Yet Implemented)
>
> This document outlines how to integrate Kata Containers for Kubernetes deployments.
> Kata provides VM-level isolation with a container-like interface.

## Overview

Kata Containers runs each container inside a lightweight VM, providing kernel-level
isolation similar to Firecracker, but with full OCI compatibility for Kubernetes.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Node                                │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       │
│  │  Regular Pod     │  │  Kata Pod (Syn137)  │  │  Kata Pod (Syn137)  │       │
│  │  (host kernel)   │  │  ┌────────────┐  │  │  ┌────────────┐  │       │
│  │                  │  │  │  VM Kernel │  │  │  │  VM Kernel │  │       │
│  │                  │  │  │  (isolated)│  │  │  │  (isolated)│  │       │
│  │                  │  │  └────────────┘  │  │  └────────────┘  │       │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘       │
│                                                                          │
│  containerd + Kata runtime (kata-qemu / kata-clh / kata-fc)             │
└─────────────────────────────────────────────────────────────────────────┘
```

## Why Kata for Kubernetes?

| Feature | gVisor | Kata Containers | Firecracker (standalone) |
|---------|--------|-----------------|--------------------------|
| **Isolation** | Syscall-level | Kernel-level | Kernel-level |
| **K8s Native** | Yes (RuntimeClass) | Yes (RuntimeClass) | No (API-based) |
| **Compatibility** | ~95% syscalls | 100% Linux | 100% Linux |
| **Overhead** | Low (~50MB) | Medium (~128MB) | Low (~5MB) |
| **Boot Time** | ~1s | ~1-2s | ~125ms |
| **OCI Compliant** | Yes | Yes | No |

## Implementation Plan

### Phase 1: KataWorkspace Class

Create `packages/syn-adapters/src/syn_adapters/workspaces/kata.py`:

```python
"""Kata Containers workspace for Kubernetes environments.

Kata provides VM-level isolation with OCI compatibility, making it
ideal for Kubernetes deployments where you need strong isolation
but want to use standard container tooling.

Requirements:
- Kubernetes cluster with Kata Containers installed
- RuntimeClass 'kata' configured
- containerd with Kata shim

See: docs/deployment/KATA-CONTAINERS-INTEGRATION.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from syn_shared.settings import IsolationBackend

from syn_adapters.workspaces.base import BaseIsolatedWorkspace

if TYPE_CHECKING:
    from syn_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig
    from syn_shared.settings import WorkspaceSecuritySettings


class KataWorkspace(BaseIsolatedWorkspace):
    """Kata Containers workspace for Kubernetes.

    Uses Kubernetes pod with RuntimeClass=kata for VM isolation.
    Each workspace runs in its own lightweight VM.
    """

    isolation_backend: ClassVar[IsolationBackend] = IsolationBackend.KATA
    RUNTIME_CLASS: ClassVar[str] = "kata"

    @classmethod
    def is_available(cls) -> bool:
        """Check if Kata is available.

        Returns True if:
        1. Running inside Kubernetes cluster
        2. Kata RuntimeClass exists
        3. Have permission to create pods
        """
        # TODO: Implement kubernetes.client checks
        # - Check for in-cluster config
        # - Verify RuntimeClass exists
        # - Check RBAC permissions
        return False

    @classmethod
    async def _create_isolation(
        cls,
        config: IsolatedWorkspaceConfig,
        security: WorkspaceSecuritySettings,
    ) -> IsolatedWorkspace:
        """Create Kata pod for workspace.

        Creates a Kubernetes pod with:
        - RuntimeClassName: kata
        - Security context matching our settings
        - Resource limits
        - Volume mounts for context injection
        """
        # TODO: Implement pod creation
        # 1. Build pod spec with security context
        # 2. Create pod via kubernetes.client
        # 3. Wait for pod to be running
        # 4. Return IsolatedWorkspace with pod_id
        raise NotImplementedError("Kata workspace not yet implemented")

    @classmethod
    async def _destroy_isolation(cls, workspace: IsolatedWorkspace) -> None:
        """Delete Kata pod."""
        # TODO: Delete pod via kubernetes.client
        raise NotImplementedError("Kata workspace not yet implemented")

    @classmethod
    async def execute_command(
        cls,
        workspace: IsolatedWorkspace,
        command: list[str],
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute command in Kata pod.

        Uses kubectl exec or kubernetes.client exec.
        """
        # TODO: Implement kubectl exec
        raise NotImplementedError("Kata workspace not yet implemented")
```

### Phase 2: Kubernetes Client Integration

Add dependency:

```toml
# pyproject.toml
[project.optional-dependencies]
kubernetes = [
    "kubernetes>=29.0.0",
]
```

Helper for pod creation:

```python
def build_kata_pod_spec(
    name: str,
    config: IsolatedWorkspaceConfig,
    security: WorkspaceSecuritySettings,
) -> dict:
    """Build Kubernetes pod spec for Kata workspace."""
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": "syn-workspaces",
            "labels": {
                "syn137.dev/component": "workspace",
                "syn137.dev/session-id": config.session_id,
            },
        },
        "spec": {
            "runtimeClassName": "kata",
            "restartPolicy": "Never",
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "fsGroup": 1000,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [{
                "name": "workspace",
                "image": "syn-workspace:latest",
                "command": ["sleep", "infinity"],
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": security.read_only_root,
                    "capabilities": {"drop": ["ALL"]},
                },
                "resources": {
                    "requests": {
                        "memory": security.max_memory,
                        "cpu": str(security.max_cpu),
                    },
                    "limits": {
                        "memory": security.max_memory,
                        "cpu": str(security.max_cpu),
                    },
                },
                "volumeMounts": [
                    {"name": "workspace", "mountPath": "/workspace"},
                ],
            }],
            "volumes": [
                {"name": "workspace", "emptyDir": {"sizeLimit": security.max_workspace_size}},
            ],
        },
    }
```

### Phase 3: Router Integration

Update router to include Kata:

```python
# In router.py
BACKEND_PRIORITY = [
    IsolationBackend.FIRECRACKER,  # Strongest, standalone
    IsolationBackend.KATA,          # Strongest, Kubernetes
    IsolationBackend.GVISOR,
    IsolationBackend.DOCKER_HARDENED,
    IsolationBackend.CLOUD,
]

BACKEND_CLASSES = {
    IsolationBackend.KATA: KataWorkspace,  # Add this
    # ... existing backends
}
```

## Cluster Setup

### Install Kata Containers

```bash
# Using kata-deploy (official)
kubectl apply -f https://raw.githubusercontent.com/kata-containers/kata-containers/main/tools/packaging/kata-deploy/kata-deploy.yaml

# Wait for installation
kubectl -n kube-system wait --for=condition=ready pod -l name=kata-deploy --timeout=300s

# Verify installation
kubectl get runtimeclass
# NAME   HANDLER   AGE
# kata   kata      1m
```

### Configure RuntimeClass

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
overhead:
  podFixed:
    memory: "160Mi"
    cpu: "250m"
scheduling:
  nodeSelector:
    katacontainers.io/kata-runtime: "true"
```

### Namespace Setup

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: syn-workspaces
  labels:
    pod-security.kubernetes.io/enforce: restricted
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: workspace-quota
  namespace: syn-workspaces
spec:
  hard:
    pods: "100"
    requests.cpu: "100"
    requests.memory: "100Gi"
    limits.cpu: "200"
    limits.memory: "200Gi"
```

## Testing

```bash
# Create test pod with Kata runtime
kubectl run kata-test \
    --image=python:3.12-slim \
    --restart=Never \
    --rm -it \
    --overrides='{"spec": {"runtimeClassName": "kata"}}' \
    -- python -c "print('Hello from Kata VM!')"

# Verify isolation
kubectl exec kata-test -- uname -r
# Should show Kata's guest kernel, not host kernel
```

## Comparison with Other Backends

### When to Use Kata

✅ **Use Kata when:**
- Running on Kubernetes
- Need OCI compatibility
- Want VM isolation with container UX
- Using cloud Kubernetes (EKS, GKE, AKS)

❌ **Don't use Kata when:**
- Running standalone (use Firecracker)
- Need sub-second boot times
- Limited memory (Kata has ~160MB overhead)

### Isolation Comparison

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Isolation Strength                                │
│                                                                          │
│  ████████████████████████████████████████████  Firecracker (Strongest)  │
│  ██████████████████████████████████████████    Kata Containers          │
│  █████████████████████████████                  gVisor                   │
│  █████████████████                              Hardened Docker          │
│  ██████████                                     Standard Docker          │
│  ██                                             Process (no isolation)   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Timeline

| Phase | Task | Status | ETA |
|-------|------|--------|-----|
| 1 | Create KataWorkspace class | Not Started | TBD |
| 2 | Kubernetes client integration | Not Started | TBD |
| 3 | Router integration | Not Started | TBD |
| 4 | Testing & documentation | Not Started | TBD |

## Related Documentation

- [Kata Containers Official Docs](https://katacontainers.io/docs/)
- [ADR-021: Isolated Workspace Architecture](../adrs/ADR-021-isolated-workspace-architecture.md)
- [Production Deployment Guide](./PRODUCTION-DEPLOYMENT.md)
- [Firecracker Setup](../../docker/firecracker/README.md)
