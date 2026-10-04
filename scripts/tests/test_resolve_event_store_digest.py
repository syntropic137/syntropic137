"""Unit tests for the event-store pin (#1515).

These drive the verdict functions directly. The invariant under test: the
release pins the event-store image for the ESP version at the vendored gitlink,
or it fails. There is no path to any other tag, `latest` included.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.resolve_event_store_digest import (
    IMAGE,
    LookupResult,
    ResolveError,
    _run,
    classify_lookup,
    image_tag,
    parse_esp_version,
    resolve,
    verify_index,
)

pytestmark = pytest.mark.unit

#: Captured from the real `event-store:v0.15.1` index with `imagetools inspect
#: --raw`. arm64 sorts FIRST in it, which is the ordering that made #1519 pin a
#: child manifest, and it carries `unknown/unknown` attestation entries.
_INDEX_RAW = (
    Path(__file__).parent / "fixtures" / "imagetools_event_store_index_raw.json"
).read_text()
DIGEST = "sha256:63df7cc4a09974a7b979e6cd59def2507496751e7f52d47c3bf02a3e3763a760"
GITLINK = "850078b2a65facac14a6556281475be0c66c8b67"
REF = f"{IMAGE}:v0.15.1"


class TestVersionAtTheGitlink:
    def test_reads_the_root_package_json_version(self) -> None:
        assert (
            parse_esp_version('{"name": "event-sourcing-platform", "version": "0.15.1"}')
            == "0.15.1"
        )

    def test_accepts_a_prerelease(self) -> None:
        assert parse_esp_version('{"version": "0.16.0-rc.1"}') == "0.16.0-rc.1"

    @pytest.mark.parametrize(
        "text",
        [
            '{"name": "x"}',
            '{"version": 15}',
            '{"version": "latest"}',
            '{"version": ""}',
            "[]",
            "not json",
        ],
    )
    def test_refuses_anything_that_is_not_a_semver(self, text: str) -> None:
        with pytest.raises(ResolveError):
            parse_esp_version(text)

    def test_tag_is_the_v_prefixed_release_tag(self) -> None:
        """ESP's release-container.yml tags with the GitHub release tag name."""
        assert image_tag("0.15.1") == "v0.15.1"


class TestLookupClassification:
    def test_success_is_the_digest(self) -> None:
        assert classify_lookup(REF, 0, f"{DIGEST}\n") == LookupResult(digest=DIGEST)

    def test_success_with_a_malformed_digest_is_an_error(self) -> None:
        result = classify_lookup(REF, 0, "sha256:abc\n")
        assert result.error is not None
        assert result.digest is None

    def test_the_exact_absent_line_is_absent(self) -> None:
        """Measured against GHCR: `ERROR: <ref>: not found`."""
        assert classify_lookup(REF, 1, f"ERROR: {REF}: not found\n") == LookupResult(absent=True)

    @pytest.mark.parametrize(
        "output",
        [
            "ERROR: failed to authorize: 401 Unauthorized\n",
            "ERROR: unexpected status: 500, credential helper not found\n",
            f"ERROR: {IMAGE}:v0.15.0: not found\n",  # a DIFFERENT ref
            "docker: 'buildx' is not a docker command.\n",
        ],
    )
    def test_any_other_failure_is_an_error_not_absent(self, output: str) -> None:
        """A failure that merely mentions "not found" must not read as absent."""
        result = classify_lookup(REF, 1, output)
        assert result.error is not None
        assert not result.absent


class TestMissingTooling:
    def test_a_missing_binary_is_a_resolve_error_not_a_traceback(self) -> None:
        """No docker CLI (an agent workspace) must fail the gate cleanly."""
        with pytest.raises(ResolveError, match="could not run"):
            _run(["definitely-not-a-binary-1515", "x"])


class TestNoFallback:
    def test_a_published_tag_resolves(self) -> None:
        assert resolve(GITLINK, "0.15.1", LookupResult(digest=DIGEST)) == DIGEST

    def test_an_unpublished_tag_fails_the_release(self) -> None:
        """The #1515 acceptance: absent means fail, never `latest`."""
        with pytest.raises(ResolveError, match=r"event-store:v0\.15\.1 is not published"):
            resolve(GITLINK, "0.15.1", LookupResult(absent=True))

    def test_the_failure_names_the_gitlink_and_version(self) -> None:
        with pytest.raises(ResolveError) as exc:
            resolve(GITLINK, "0.15.1", LookupResult(absent=True))
        assert GITLINK in str(exc.value)
        assert "0.15.1" in str(exc.value)

    def test_a_lookup_error_fails_the_release(self) -> None:
        with pytest.raises(ResolveError, match="401"):
            resolve(GITLINK, "0.15.1", LookupResult(error="401 Unauthorized"))

    def test_the_module_never_names_latest_as_a_tag(self) -> None:
        """No code path may build a `:latest` ref. Checked at the source,
        because the fallback this replaced was a single extra line."""
        source = (Path(__file__).parents[1] / "resolve_event_store_digest.py").read_text()
        assert ":latest" not in source
        assert "'latest'" not in source
        assert '"latest"' not in source


class TestIndexVerification:
    def test_the_real_index_passes(self) -> None:
        verify_index(DIGEST, _INDEX_RAW)

    def test_a_single_platform_manifest_fails(self) -> None:
        """What `manifest inspect --verbose | .[0]` pinned in #1519."""
        child = json.dumps(
            {"mediaType": "application/vnd.oci.image.manifest.v1+json", "layers": []}
        )
        with pytest.raises(ResolveError, match="not a manifest index"):
            verify_index(DIGEST, child)

    @pytest.mark.parametrize("drop", ["amd64", "arm64"])
    def test_an_index_missing_a_required_arch_fails(self, drop: str) -> None:
        doc = json.loads(_INDEX_RAW)
        doc["manifests"] = [m for m in doc["manifests"] if m["platform"]["architecture"] != drop]
        with pytest.raises(ResolveError, match=f"linux/{drop}"):
            verify_index(DIGEST, json.dumps(doc))

    def test_unknown_platform_attestations_do_not_count(self) -> None:
        doc = json.loads(_INDEX_RAW)
        doc["manifests"] = [m for m in doc["manifests"] if m["platform"]["os"] == "unknown"]
        with pytest.raises(ResolveError, match="linux/amd64"):
            verify_index(DIGEST, json.dumps(doc))

    def test_garbage_fails(self) -> None:
        with pytest.raises(ResolveError):
            verify_index(DIGEST, "not json")
