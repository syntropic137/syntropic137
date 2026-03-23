"""Regression tests for organization/system/repo create → list → show round-trip.

These tests caught the bug where POST /organizations succeeded but GET /organizations
returned empty because OrganizationProjection was not wired into the ProjectionManager.

All tests run with in-memory storage (APP_ENVIRONMENT=test, no external services).
"""

import os

import pytest

from syn_api.types import Err, Ok, OrganizationError

os.environ.setdefault("APP_ENVIRONMENT", "test")


# ---------------------------------------------------------------------------
# Organization round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_org_create_appears_in_list():
    """Created org must appear in list immediately after creation."""
    from syn_api.routes.organizations import create_organization, list_organizations

    result = await create_organization(name="Acme Corp", slug="acme-corp")
    assert isinstance(result, Ok), f"create failed: {result}"
    org_id = result.value

    list_result = await list_organizations()
    assert isinstance(list_result, Ok)
    ids = [o.organization_id for o in list_result.value]
    assert org_id in ids, f"org {org_id} missing from list: {ids}"


@pytest.mark.unit
async def test_org_create_appears_in_show():
    """Created org must be retrievable by ID."""
    from syn_api.routes.organizations import create_organization, get_organization

    result = await create_organization(name="Show Test Org", slug="show-test-org")
    assert isinstance(result, Ok)
    org_id = result.value

    get_result = await get_organization(org_id)
    assert isinstance(get_result, Ok), f"show failed: {get_result}"
    assert get_result.value.organization_id == org_id
    assert get_result.value.name == "Show Test Org"
    assert get_result.value.slug == "show-test-org"


@pytest.mark.unit
async def test_org_show_unknown_id_returns_not_found():
    """get_organization returns NOT_FOUND for an ID that was never created."""
    from syn_api.routes.organizations import get_organization

    result = await get_organization("org-nonexistent-000")
    assert isinstance(result, Err)
    assert result.error == OrganizationError.NOT_FOUND


@pytest.mark.unit
async def test_org_update_reflects_in_show():
    """Updated org name must appear in subsequent get_organization."""
    from syn_api.routes.organizations import (
        create_organization,
        get_organization,
        update_organization,
    )

    create_result = await create_organization(name="Before Update", slug="before-update")
    assert isinstance(create_result, Ok)
    org_id = create_result.value

    update_result = await update_organization(org_id, name="After Update")
    assert isinstance(update_result, Ok), f"update failed: {update_result}"

    get_result = await get_organization(org_id)
    assert isinstance(get_result, Ok)
    assert get_result.value.name == "After Update"


@pytest.mark.unit
async def test_multiple_orgs_all_appear_in_list():
    """All created orgs appear in list (not just the last one)."""
    from syn_api.routes.organizations import create_organization, list_organizations

    ids = []
    for i in range(3):
        r = await create_organization(name=f"Org {i}", slug=f"org-{i}")
        assert isinstance(r, Ok)
        ids.append(r.value)

    list_result = await list_organizations()
    assert isinstance(list_result, Ok)
    listed_ids = {o.organization_id for o in list_result.value}
    for org_id in ids:
        assert org_id in listed_ids, f"org {org_id} missing from list"


# ---------------------------------------------------------------------------
# System round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_system_create_appears_in_list():
    """Created system must appear in list immediately after creation."""
    from syn_api.routes.organizations import create_organization
    from syn_api.routes.systems import create_system, list_systems

    org_result = await create_organization(name="Sys Org", slug="sys-org")
    assert isinstance(org_result, Ok)
    org_id = org_result.value

    sys_result = await create_system(
        organization_id=org_id, name="Alpha System", description="test"
    )
    assert isinstance(sys_result, Ok), f"system create failed: {sys_result}"
    sys_id = sys_result.value

    list_result = await list_systems(organization_id=org_id)
    assert isinstance(list_result, Ok)
    ids = [s.system_id for s in list_result.value]
    assert sys_id in ids, f"system {sys_id} missing from list: {ids}"


@pytest.mark.unit
async def test_system_create_increments_org_system_count():
    """Creating a system increments the org's system_count."""
    from syn_api.routes.organizations import create_organization, get_organization
    from syn_api.routes.systems import create_system

    org_result = await create_organization(name="Count Org", slug="count-org")
    assert isinstance(org_result, Ok)
    org_id = org_result.value

    before = await get_organization(org_id)
    assert isinstance(before, Ok)
    assert before.value.system_count == 0

    await create_system(organization_id=org_id, name="S1", description="")
    await create_system(organization_id=org_id, name="S2", description="")

    after = await get_organization(org_id)
    assert isinstance(after, Ok)
    assert after.value.system_count == 2


# ---------------------------------------------------------------------------
# Repo round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_repo_register_appears_in_list():
    """Registered repo must appear in list immediately after registration."""
    from syn_api.routes.organizations import create_organization
    from syn_api.routes.repos import list_repos, register_repo

    org_result = await create_organization(name="Repo Org", slug="repo-org")
    assert isinstance(org_result, Ok)
    org_id = org_result.value

    repo_result = await register_repo(
        organization_id=org_id,
        full_name="acme/backend",
        provider="github",
    )
    assert isinstance(repo_result, Ok), f"register failed: {repo_result}"
    repo_id = repo_result.value

    list_result = await list_repos(organization_id=org_id)
    assert isinstance(list_result, Ok)
    ids = [r.repo_id for r in list_result.value]
    assert repo_id in ids, f"repo {repo_id} missing from list: {ids}"


@pytest.mark.unit
async def test_repo_register_increments_org_repo_count():
    """Registering a repo increments the org's repo_count."""
    from syn_api.routes.organizations import create_organization, get_organization
    from syn_api.routes.repos import register_repo

    org_result = await create_organization(name="RCount Org", slug="rcount-org")
    assert isinstance(org_result, Ok)
    org_id = org_result.value

    before = await get_organization(org_id)
    assert isinstance(before, Ok)
    assert before.value.repo_count == 0

    await register_repo(organization_id=org_id, full_name="acme/repo1", provider="github")
    await register_repo(organization_id=org_id, full_name="acme/repo2", provider="github")

    after = await get_organization(org_id)
    assert isinstance(after, Ok)
    assert after.value.repo_count == 2
