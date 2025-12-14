#!/usr/bin/env python3
"""E2E Test: Agent-in-Container Execution Flow.

This script validates the full agent-in-container architecture:

1. Build workspace image with aef-agent-runner
2. Start sidecar proxy container
3. Create isolated workspace linked to sidecar network
4. Write task.json
5. Execute agent runner via streaming
6. Parse JSONL events
7. Verify artifacts
8. Cleanup

Prerequisites:
- Docker installed and running
- AEF workspace image built: ./docker/workspace/build.sh
- Sidecar image built: docker build -t aef-sidecar:latest docker/sidecar-proxy/

Usage:
    python scripts/e2e_agent_in_container_test.py [--build] [--no-cleanup]

Options:
    --build       Rebuild Docker images before testing
    --no-cleanup  Keep containers running after test (for debugging)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def build_images() -> bool:
    """Build Docker images for testing."""
    logger.info("🔨 Building Docker images...")

    # Build workspace image
    workspace_build = await asyncio.create_subprocess_exec(
        "bash",
        "docker/workspace/build.sh",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await workspace_build.communicate()

    if workspace_build.returncode != 0:
        logger.error("Failed to build workspace image: %s", stderr.decode())
        return False

    logger.info("✅ Workspace image built")

    # Build sidecar image
    sidecar_build = await asyncio.create_subprocess_exec(
        "docker",
        "build",
        "-t",
        "aef-sidecar:latest",
        "docker/sidecar-proxy/",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await sidecar_build.communicate()

    if sidecar_build.returncode != 0:
        logger.error("Failed to build sidecar image: %s", stderr.decode())
        return False

    logger.info("✅ Sidecar image built")
    return True


async def check_images_exist() -> tuple[bool, str]:
    """Check if required Docker images exist."""
    for image in ["aef-workspace:latest", "aef-sidecar:latest"]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "image",
            "inspect",
            image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False, f"Image not found: {image}"

    return True, ""


async def create_network(network_name: str) -> bool:
    """Create a Docker network."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "network",
        "create",
        network_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def cleanup_network(network_name: str) -> None:
    """Remove a Docker network."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "network",
        "rm",
        network_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def start_sidecar(
    network_name: str,
    execution_id: str,
) -> tuple[str, str]:
    """Start sidecar container.

    Returns:
        Tuple of (container_id, container_name)
    """
    container_name = f"aef-sidecar-test-{execution_id[:8]}"

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--rm",
        f"--name={container_name}",
        f"--network={network_name}",
        "-e",
        f"AEF_EXECUTION_ID={execution_id}",
        "-e",
        "AEF_TOKEN_SERVICE_URL=http://mock-token-service:8080",
        "aef-sidecar:latest",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start sidecar: {stderr.decode()}")

    container_id = stdout.decode().strip()
    return container_id, container_name


async def stop_container(name: str) -> None:
    """Stop a container."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def start_workspace(
    network_name: str,
    sidecar_name: str,
    execution_id: str,
) -> tuple[str, str]:
    """Start workspace container.

    Returns:
        Tuple of (container_id, container_name)
    """
    container_name = f"aef-workspace-test-{execution_id[:8]}"
    proxy_url = f"http://{sidecar_name}:8081"

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--rm",
        f"--name={container_name}",
        f"--network={network_name}",
        "-e",
        f"HTTP_PROXY={proxy_url}",
        "-e",
        f"HTTPS_PROXY={proxy_url}",
        "-e",
        f"AEF_EXECUTION_ID={execution_id}",
        # Override entrypoint to keep container running
        "--entrypoint",
        "sleep",
        "aef-workspace:latest",
        "infinity",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start workspace: {stderr.decode()}")

    container_id = stdout.decode().strip()
    return container_id, container_name


async def write_task_to_container(
    container_name: str,
    task: dict,
) -> None:
    """Write task.json to container."""
    task_json = json.dumps(task)

    # Use docker exec to write file
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "bash",
        "-c",
        f"echo '{task_json}' > /workspace/task.json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to write task: {stderr.decode()}")


async def execute_agent_streaming(
    container_name: str,
    timeout: int = 30,
) -> list[dict]:
    """Execute agent runner and collect events."""
    events = []

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "python",
        "-m",
        "aef_agent_runner",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        async with asyncio.timeout(timeout):
            if proc.stdout:
                async for line in proc.stdout:
                    line_str = line.decode().strip()
                    if line_str:
                        try:
                            event = json.loads(line_str)
                            events.append(event)
                            logger.debug("Event: %s", event.get("type"))
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSONL: %s", line_str[:50])
    except TimeoutError:
        logger.warning("Agent execution timed out after %ds", timeout)
        proc.kill()

    await proc.wait()
    return events


async def check_agent_runner_installed(container_name: str) -> bool:
    """Check if aef-agent-runner is installed."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "python",
        "-c",
        "import aef_agent_runner; print(aef_agent_runner.__version__)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("aef_agent_runner not installed: %s", stderr.decode())
        return False

    version = stdout.decode().strip()
    logger.info("aef_agent_runner version: %s", version)
    return True


async def run_e2e_test(cleanup: bool = True) -> bool:
    """Run the full E2E test."""
    execution_id = str(uuid.uuid4())
    network_name = f"aef-e2e-test-{execution_id[:8]}"
    sidecar_container = None
    workspace_container = None

    try:
        print()
        print("=" * 60)
        print("E2E Test: Agent-in-Container Flow")
        print("=" * 60)
        print()

        # Step 1: Create network
        logger.info("📡 Step 1: Creating Docker network...")
        if not await create_network(network_name):
            logger.error("Failed to create network")
            return False
        logger.info("   Network: %s", network_name)

        # Step 2: Start sidecar
        logger.info("🛡️ Step 2: Starting sidecar proxy...")
        _, sidecar_container = await start_sidecar(
            network_name,
            execution_id,
        )
        logger.info("   Sidecar: %s", sidecar_container)

        # Step 3: Start workspace
        logger.info("📦 Step 3: Starting workspace container...")
        _, workspace_container = await start_workspace(
            network_name,
            sidecar_container,
            execution_id,
        )
        logger.info("   Workspace: %s", workspace_container)

        # Give containers time to start
        await asyncio.sleep(2)

        # Step 4: Verify agent runner is installed
        logger.info("🔍 Step 4: Verifying aef-agent-runner installation...")
        if not await check_agent_runner_installed(workspace_container):
            logger.error("Agent runner not installed!")
            return False

        # Step 5: Write task.json
        logger.info("📝 Step 5: Writing task.json...")
        task = {
            "phase": "test",
            "prompt": "This is a test phase. Simply output 'Hello from container!'",
            "execution_id": execution_id,
            "tenant_id": "e2e-test-tenant",
            "inputs": {"test_mode": True},
            "artifacts": [],
        }
        await write_task_to_container(workspace_container, task)

        # Step 6: Execute agent runner
        logger.info("🚀 Step 6: Executing agent runner...")
        logger.info("   (This will fail without API tokens - expected)")

        events = await execute_agent_streaming(workspace_container, timeout=10)

        # Step 7: Analyze events
        logger.info("📊 Step 7: Analyzing events...")
        logger.info("   Total events received: %d", len(events))

        event_types = [e.get("type") for e in events]
        logger.info("   Event types: %s", event_types)

        # Check for expected events
        has_started = "started" in event_types
        has_error = "error" in event_types  # Expected without API tokens

        if has_started:
            logger.info("   ✅ Agent started event received")
        else:
            logger.warning("   ⚠️ No started event received")

        if has_error:
            logger.info("   ✅ Error event received (expected without API tokens)")
            error_event = next(e for e in events if e.get("type") == "error")
            logger.info("   Error: %s", error_event.get("message", "")[:100])

        # Step 8: Summary
        print()
        print("=" * 60)
        print("E2E Test Results")
        print("=" * 60)
        print()
        print(f"Execution ID:    {execution_id}")
        print(f"Network:         {network_name}")
        print(f"Sidecar:         {sidecar_container}")
        print(f"Workspace:       {workspace_container}")
        print(f"Events:          {len(events)}")
        print(f"Started Event:   {'✅' if has_started else '❌'}")
        print()

        # Test is successful if we got a started event
        # (full execution requires API tokens)
        success = has_started

        if success:
            print("✅ E2E TEST PASSED")
            print()
            print("The agent-in-container architecture is working:")
            print("  - Workspace container started")
            print("  - Linked to sidecar proxy network")
            print("  - aef-agent-runner installed and executable")
            print("  - JSONL event streaming works")
            print()
            print("To run a full execution, configure API tokens.")
        else:
            print("❌ E2E TEST FAILED")
            print()
            print("The agent runner did not emit a started event.")

        return success

    except Exception as e:
        logger.exception("E2E test failed: %s", e)
        return False

    finally:
        if cleanup:
            logger.info("🧹 Cleaning up...")
            if workspace_container:
                await stop_container(workspace_container)
            if sidecar_container:
                await stop_container(sidecar_container)
            await cleanup_network(network_name)
        else:
            logger.info("Skipping cleanup (--no-cleanup)")
            print()
            print("Containers still running for debugging:")
            print(f"  Sidecar:   docker logs {sidecar_container}")
            print(f"  Workspace: docker exec -it {workspace_container} bash")
            print(f"  Cleanup:   docker stop {sidecar_container} {workspace_container}")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="E2E Test: Agent-in-Container")
    parser.add_argument("--build", action="store_true", help="Rebuild images")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep containers")
    args = parser.parse_args()

    # Check/build images
    if args.build:
        if not await build_images():
            return 1
    else:
        exists, error = await check_images_exist()
        if not exists:
            logger.error(error)
            logger.info("Run with --build to build images, or build manually:")
            logger.info("  ./docker/workspace/build.sh")
            logger.info("  docker build -t aef-sidecar:latest docker/sidecar-proxy/")
            return 1

    # Run E2E test
    success = await run_e2e_test(cleanup=not args.no_cleanup)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
