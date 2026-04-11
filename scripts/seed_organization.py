"""Seed a default organization, system, and repos via the HTTP API.

Creates the Syntropic137 organization with its core repos grouped
into a system.  Attempts to skip entities that already exist, but
idempotency depends on persistent projections (see #222) — duplicates
may be created on restart if projections have not caught up.

Requires the API server to be running (just dev or just api-backend).
Called by `just seed-organization`.

Usage:
    uv run python scripts/seed_organization.py [--dry-run] [--api-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx

from syn_shared.settings.dev_tooling import get_dev_api_url

logger = logging.getLogger(__name__)


# --- Seed data -----------------------------------------------------------

ORGANIZATION = {
    "name": "Syntropic137",
    "slug": "syntropic137",
}

SYSTEM = {
    "name": "syn-engineer",
    "description": "AI-powered engineering agent - orchestration, observability, and CLI",
}

REPOS = [
    {
        "full_name": "syntropic137/syntropic137",
        "owner": "syntropic137",
        "default_branch": "main",
        "is_private": True,
    },
    {
        "full_name": "syntropic137/sandbox_syn-engineer-beta",
        "owner": "syntropic137",
        "default_branch": "main",
        "is_private": False,
    },
]

DEFAULT_API_URL = get_dev_api_url()


# --- Seed logic -----------------------------------------------------------


async def _seed(api_url: str, dry_run: bool) -> int:
    async with httpx.AsyncClient(base_url=api_url, timeout=15.0) as client:
        # --- Organization ---
        resp = await client.get("/organizations")
        resp.raise_for_status()
        existing_orgs = resp.json().get("organizations", [])
        org_id: str | None = None

        for o in existing_orgs:
            if o.get("slug") == ORGANIZATION["slug"]:
                org_id = o["organization_id"]
                break

        if org_id:
            print(f"  ○ Organization '{ORGANIZATION['name']}' already exists ({org_id[:12]}...)")
        elif dry_run:
            print(f"  ⊘ Organization '{ORGANIZATION['name']}' (dry run — would create)")
        else:
            resp = await client.post(
                "/organizations",
                json={
                    "name": ORGANIZATION["name"],
                    "slug": ORGANIZATION["slug"],
                    "created_by": "seed-script",
                },
            )
            resp.raise_for_status()
            org_id = resp.json().get("organization_id")
            print(
                f"  ✓ Organization '{ORGANIZATION['name']}' created ({org_id[:12] if org_id else '?'}...)"
            )

        if not org_id and not dry_run:
            print("  ✗ Cannot proceed without organization_id")
            return 1

        # --- System ---
        params = {"organization_id": org_id} if org_id else {}
        resp = await client.get("/systems", params=params)
        resp.raise_for_status()
        existing_systems = resp.json().get("systems", [])
        system_id: str | None = None

        for s in existing_systems:
            if s.get("name") == SYSTEM["name"]:
                system_id = s["system_id"]
                break

        if system_id:
            print(f"  ○ System '{SYSTEM['name']}' already exists ({system_id[:12]}...)")
        elif dry_run:
            print(f"  ⊘ System '{SYSTEM['name']}' (dry run — would create)")
        else:
            resp = await client.post(
                "/systems",
                json={
                    "organization_id": org_id,
                    "name": SYSTEM["name"],
                    "description": SYSTEM["description"],
                    "created_by": "seed-script",
                },
            )
            resp.raise_for_status()
            system_id = resp.json().get("system_id")
            print(
                f"  ✓ System '{SYSTEM['name']}' created ({system_id[:12] if system_id else '?'}...)"
            )

        # --- Repos ---
        params = {"organization_id": org_id} if org_id else {}
        resp = await client.get("/repos", params=params)
        resp.raise_for_status()
        existing_repos = resp.json().get("repos", [])
        existing_names: dict[str, str] = {r["full_name"]: r["repo_id"] for r in existing_repos}

        for repo_def in REPOS:
            full_name = repo_def["full_name"]
            if full_name in existing_names:
                rid = existing_names[full_name]
                print(f"  ○ Repo '{full_name}' already exists ({rid[:12]}...)")
            elif dry_run:
                print(f"  ⊘ Repo '{full_name}' (dry run — would register)")
            else:
                resp = await client.post(
                    "/repos",
                    json={
                        "organization_id": org_id,
                        "full_name": full_name,
                        "provider": "github",
                        "owner": repo_def.get("owner", ""),
                        "default_branch": repo_def.get("default_branch", "main"),
                        "is_private": repo_def.get("is_private", False),
                        "created_by": "seed-script",
                    },
                )
                resp.raise_for_status()
                rid = resp.json().get("repo_id", "")
                existing_names[full_name] = rid
                print(f"  ✓ Repo '{full_name}' registered ({rid[:12]}...)")

        # --- Assign repos to system ---
        if system_id and not dry_run:
            for repo_def in REPOS:
                full_name = str(repo_def["full_name"])
                rid = existing_names.get(full_name)
                if rid:
                    resp = await client.post(
                        f"/repos/{rid}/assign",
                        json={
                            "system_id": system_id,
                        },
                    )
                    if resp.status_code == 200:
                        print(f"  ✓ Assigned '{full_name}' → system '{SYSTEM['name']}'")
                    elif resp.status_code == 409:
                        print(f"  ○ '{full_name}' → system (already assigned)")
                    else:
                        logger.warning(
                            "Unexpected status %d assigning repo '%s' to system: %s",
                            resp.status_code,
                            full_name,
                            resp.text,
                        )
        elif dry_run:
            for repo_def in REPOS:
                print(f"  ⊘ Assign '{repo_def['full_name']}' → system (dry run)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed organization, system, and repos")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without creating entities",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})",
    )
    args = parser.parse_args()

    print("🌱 Seeding organization data...\n")
    try:
        exit_code = asyncio.run(_seed(args.api_url, args.dry_run))
    except httpx.ConnectError:
        print("  ✗ Cannot connect to API server. Is it running? (just dev or just api-backend)")
        sys.exit(1)

    if exit_code == 0:
        print("\n✅ Organization seed complete!")
    else:
        print("\n❌ Seed failed")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
