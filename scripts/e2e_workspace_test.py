#!/usr/bin/env python3
"""End-to-end test: Agent working in isolated Docker workspace.

This script tests the full workflow:
1. Create isolated Docker container
2. Clone a real git repository inside it
3. Run work (install deps, run tests, make changes)
4. Collect artifacts
5. Verify isolation was maintained

Usage:
    uv run python scripts/e2e_workspace_test.py

    # Test with network access (needed for git clone)
    uv run python scripts/e2e_workspace_test.py --allow-network

    # Use specific backend
    uv run python scripts/e2e_workspace_test.py --backend gvisor
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Test repo - small, public, fast to clone
TEST_REPO = "https://github.com/keleshev/schema.git"  # Tiny Python lib
TEST_REPO_NAME = "schema"


class E2EWorkspaceTest:
    """End-to-end workspace test runner."""

    def __init__(
        self,
        backend: str = "docker_hardened",
        allow_network: bool = False,
        verbose: bool = False,
    ) -> None:
        self.backend = backend
        self.allow_network = allow_network
        self.verbose = verbose
        self.container_id: str | None = None
        self.container_name = "aef-e2e-test"

    def log(self, msg: str) -> None:
        """Print message."""
        print(f"  {msg}")

    def run_host(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run command on host."""
        if self.verbose:
            print(f"  [HOST] {' '.join(cmd)}")
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    async def run_container(
        self, cmd: list[str], timeout: int = 60, check: bool = True
    ) -> tuple[int, str, str]:
        """Run command in container."""
        if not self.container_id:
            raise RuntimeError("Container not started")

        full_cmd = ["docker", "exec", self.container_id, *cmd]
        if self.verbose:
            print(f"  [CONTAINER] {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode or 0

            if check and exit_code != 0:
                print(f"  ❌ Command failed: {' '.join(cmd)}")
                print(f"     stdout: {stdout.decode()[:200]}")
                print(f"     stderr: {stderr.decode()[:200]}")

            return exit_code, stdout.decode(), stderr.decode()
        except TimeoutError:
            proc.kill()
            return -1, "", "Timeout"

    async def start_container(self) -> bool:
        """Start the test container."""
        # Remove any existing container
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
        )

        # Build docker run command
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            self.container_name,
        ]

        # Runtime for gVisor
        if self.backend == "gvisor":
            cmd.extend(["--runtime", "runsc"])

        # Network - need it for git clone
        if self.allow_network:
            cmd.extend(["--network", "bridge"])
        else:
            cmd.extend(["--network", "none"])

        # Security settings
        # Note: We use bitnami/git which has git pre-installed
        # and we add Python for our tests
        cmd.extend(
            [
                "--memory",
                "1g",
                "--cpus",
                "1",
                "--pids-limit",
                "200",  # Higher for package installs
                # Don't drop ALL caps - need some for networking
                "--cap-drop=SYS_ADMIN",
                "--cap-drop=NET_ADMIN",
                "--cap-drop=SYS_PTRACE",
                "--cap-drop=MKNOD",
                "--security-opt=no-new-privileges:true",
                "--env",
                "HOME=/workspace",
                "--workdir",
                "/workspace",
                # Use python image with git
                "python:3.12-slim",
                "sleep",
                "600",
            ]
        )

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Failed to start container: {result.stderr}")
            return False

        self.container_id = result.stdout.strip()[:12]
        self.log(f"Container started: {self.container_id}")

        # Wait for container to be ready
        await asyncio.sleep(1)
        return True

    async def stop_container(self) -> None:
        """Stop and remove the test container."""
        if self.container_id:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                capture_output=True,
            )
            self.log("Container stopped")

    async def install_git(self) -> bool:
        """Install git in container."""
        self.log("Installing git...")
        exit_code, _stdout, _stderr = await self.run_container(
            ["apt-get", "update"], timeout=120, check=False
        )
        if exit_code != 0:
            print("❌ apt-get update failed")
            return False

        exit_code, _stdout, stderr = await self.run_container(
            ["apt-get", "install", "-y", "git"], timeout=120, check=False
        )
        if exit_code != 0:
            print(f"❌ git install failed: {stderr}")
            return False

        self.log("✅ Git installed")
        return True

    async def clone_repo(self) -> bool:
        """Clone the test repository."""
        self.log(f"Cloning {TEST_REPO}...")
        exit_code, _stdout, stderr = await self.run_container(
            ["git", "clone", "--depth", "1", TEST_REPO, TEST_REPO_NAME],
            timeout=60,
            check=False,
        )

        if exit_code != 0:
            print(f"❌ Clone failed: {stderr}")
            return False

        self.log(f"✅ Cloned {TEST_REPO_NAME}")
        return True

    async def run_work(self) -> bool:
        """Simulate agent work: install deps, run tests, make changes."""
        self.log("Installing dependencies...")

        # Install the package
        exit_code, stdout, stderr = await self.run_container(
            ["pip", "install", "-e", f"/workspace/{TEST_REPO_NAME}"],
            timeout=120,
            check=False,
        )
        if exit_code != 0:
            print(f"❌ pip install failed: {stderr}")
            return False
        self.log("✅ Dependencies installed")

        # Run Python to verify it works
        self.log("Running code...")
        exit_code, stdout, stderr = await self.run_container(
            [
                "python",
                "-c",
                f"import {TEST_REPO_NAME}; print(f'{TEST_REPO_NAME} version:', getattr({TEST_REPO_NAME}, '__version__', 'unknown'))",
            ],
            check=False,
        )
        if exit_code != 0:
            print(f"❌ Import failed: {stderr}")
            return False
        self.log(f"✅ Code executed: {stdout.strip()}")

        # Create an output file (simulating agent work)
        self.log("Creating output file...")
        exit_code, _, _ = await self.run_container(
            [
                "python",
                "-c",
                f"""
import json
import os

# Simulate agent generating output
output = {{
    "status": "success",
    "repo": "{TEST_REPO_NAME}",
    "files_found": len(os.listdir("/workspace/{TEST_REPO_NAME}")),
    "python_version": __import__("sys").version,
}}

with open("/workspace/output.json", "w") as f:
    json.dump(output, f, indent=2)

print("Output written to /workspace/output.json")
""",
            ],
            check=False,
        )
        if exit_code != 0:
            return False
        self.log("✅ Output file created")

        return True

    async def verify_isolation(self) -> bool:
        """Verify isolation is working."""
        self.log("Verifying isolation...")

        # Check we can't see host processes
        exit_code, stdout, _ = await self.run_container(["ls", "/proc"], check=False)
        procs = [p for p in stdout.split() if p.isdigit()]
        if len(procs) > 10:
            print(f"❌ Too many processes visible: {len(procs)}")
            return False
        self.log(f"✅ Process isolation: only {len(procs)} processes visible")

        # Check capabilities are dropped
        exit_code, stdout, _ = await self.run_container(["cat", "/proc/self/status"], check=False)
        if "CapEff:\t0000000000000000" in stdout:
            self.log("✅ Capabilities dropped")
        else:
            print("⚠️  Some capabilities may remain")

        # Check network (if supposed to be isolated)
        if not self.allow_network:
            exit_code, _, _ = await self.run_container(
                [
                    "python",
                    "-c",
                    "import socket; socket.create_connection(('8.8.8.8', 53), timeout=2)",
                ],
                timeout=5,
                check=False,
            )
            if exit_code == 0:
                print("❌ Network should be blocked but isn't")
                return False
            self.log("✅ Network isolated")

        return True

    async def collect_output(self) -> bool:
        """Collect the output file."""
        self.log("Collecting output...")

        # Copy file from container
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "docker",
                    "cp",
                    f"{self.container_name}:/workspace/output.json",
                    tmpdir,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"❌ Failed to collect output: {result.stderr}")
                return False

            output_path = Path(tmpdir) / "output.json"
            if output_path.exists():
                import json

                data = json.loads(output_path.read_text())
                self.log(f"✅ Collected output: {data}")
                return True

        return False

    async def run(self) -> bool:
        """Run the full E2E test."""
        print("\n" + "=" * 60)
        print("🧪 E2E Workspace Test: Agent Working in Isolation")
        print(f"   Backend: {self.backend}")
        print(f"   Network: {'enabled' if self.allow_network else 'disabled'}")
        print("=" * 60 + "\n")

        # Check Docker
        if not shutil.which("docker"):
            print("❌ Docker not found")
            return False

        try:
            # Start container
            print("1️⃣  Starting isolated container...")
            if not await self.start_container():
                return False

            # For git clone, we need network
            if self.allow_network:
                # Install git and clone
                print("\n2️⃣  Installing git...")
                if not await self.install_git():
                    return False

                print("\n3️⃣  Cloning repository...")
                if not await self.clone_repo():
                    return False

                print("\n4️⃣  Running agent work...")
                if not await self.run_work():
                    return False

                print("\n5️⃣  Collecting output...")
                if not await self.collect_output():
                    return False
            else:
                print("\n⚠️  Network disabled - skipping git clone test")
                print("   Run with --allow-network to test full workflow")

            print("\n6️⃣  Verifying isolation...")
            if not await self.verify_isolation():
                return False

        finally:
            print("\n7️⃣  Cleaning up...")
            await self.stop_container()

        print("\n" + "=" * 60)
        print("🎉 E2E Test PASSED!")
        print("=" * 60 + "\n")

        return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="E2E workspace test")
    parser.add_argument(
        "--backend",
        choices=["gvisor", "docker_hardened"],
        default="docker_hardened",
        help="Isolation backend",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow network (needed for git clone)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    test = E2EWorkspaceTest(
        backend=args.backend,
        allow_network=args.allow_network,
        verbose=args.verbose,
    )

    success = await test.run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
