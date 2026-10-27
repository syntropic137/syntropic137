"""`just e2b-template-build` builds from the pins and writes a receipt (AW#91).

Fakes stand in for cosign, docker and E2B: no real E2B here (owner rule).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from agentic_isolation.providers.e2b_template import E2BTemplateBuild, E2BTemplateSpec
from scripts.e2b_template_build import (
    SDK_KEY_VARIABLE,
    SYN_KEY_VARIABLE,
    TemplateBuildError,
    TemplateReceipt,
    bridge_sdk_key,
    build,
    main,
)

from syn_adapters.workspace_backends.e2b.template_ref import expected_template_name
from syn_shared.settings.workspace_images import (
    E2B_DOCKER_PRE_PULLS,
    E2B_DOCKER_TEMPLATE_PROVIDER,
    PINNED_DIGESTS,
    workspace_image_ref,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_MANIFEST = "sha256:" + "ef" * 32


class _Reader:
    def __init__(self, *, verifies: bool = True) -> None:
        self.verifies = verifies
        self.calls: list[tuple[str, str]] = []

    def verify(self, image: str) -> None:
        self.calls.append(("verify", image))
        if not self.verifies:
            raise TemplateBuildError(f"{image} failed cosign")

    def manifest_hash(self, image: str) -> str:
        self.calls.append(("manifest", image))
        return _MANIFEST


class _Builder:
    def __init__(self) -> None:
        self.specs: list[E2BTemplateSpec] = []

    async def build(self, spec: E2BTemplateSpec) -> E2BTemplateBuild:
        self.specs.append(spec)
        return E2BTemplateBuild(template_id="tpl-123", build_id="bld-456", spec=spec)


def _build(reader: _Reader, builder: _Builder, receipts: Path) -> TemplateReceipt:
    return asyncio.run(build(reader, builder, cpu_count=2, memory_mb=4096, receipt_dir=receipts))


def test_the_build_is_named_and_based_on_the_current_pins(tmp_path: Path) -> None:
    builder = _Builder()
    _build(_Reader(), builder, tmp_path)
    (spec,) = builder.specs
    assert spec.name == expected_template_name()
    assert spec.image == workspace_image_ref(E2B_DOCKER_TEMPLATE_PROVIDER)
    assert spec.verified_oci_digest == PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER]
    assert spec.expected_manifest_hash == _MANIFEST
    assert (spec.cpu_count, spec.memory_mb) == (2, 4096)
    assert spec.docker is not None
    assert [(p.reference, p.digest) for p in spec.docker.pre_pull] == [
        (p.reference, p.digest) for p in E2B_DOCKER_PRE_PULLS
    ]


def test_the_base_is_verified_before_its_manifest_is_read(tmp_path: Path) -> None:
    reader = _Reader()
    _build(reader, _Builder(), tmp_path)
    image = workspace_image_ref(E2B_DOCKER_TEMPLATE_PROVIDER)
    assert reader.calls == [("verify", image), ("manifest", image)]


def test_an_unverified_base_is_never_built(tmp_path: Path) -> None:
    builder = _Builder()
    with pytest.raises(TemplateBuildError, match="cosign"):
        _build(_Reader(verifies=False), builder, tmp_path)
    assert builder.specs == []
    assert list(tmp_path.iterdir()) == []


def test_the_receipt_records_what_was_built_and_from_what(tmp_path: Path) -> None:
    receipt = _build(_Reader(), _Builder(), tmp_path)
    written = TemplateReceipt.model_validate_json(
        (tmp_path / f"{expected_template_name()}.json").read_text()
    )
    assert written == receipt
    assert (written.template_id, written.build_id) == ("tpl-123", "bld-456")
    assert written.name == expected_template_name()
    assert written.verified_oci_digest == PINNED_DIGESTS[E2B_DOCKER_TEMPLATE_PROVIDER]
    assert written.expected_manifest_hash == _MANIFEST
    assert written.name.endswith(written.engine_hash)
    assert [(p.reference, p.digest) for p in written.pre_pull] == [
        (p.reference, p.digest) for p in E2B_DOCKER_PRE_PULLS
    ]
    assert written.docker_versions["docker-ce"]


def test_name_only_prints_the_derived_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--name-only"]) == 0
    assert capsys.readouterr().out.strip() == expected_template_name()


def test_the_syn_key_is_bridged_to_the_sdk_variable() -> None:
    environ = {SYN_KEY_VARIABLE: "e2b_test_key_not_real"}
    bridge_sdk_key(environ)
    assert environ[SDK_KEY_VARIABLE] == "e2b_test_key_not_real"


def test_an_sdk_key_alone_is_used_as_it_is() -> None:
    environ = {SDK_KEY_VARIABLE: "sdk_test_key_not_real"}
    bridge_sdk_key(environ)
    assert environ == {SDK_KEY_VARIABLE: "sdk_test_key_not_real"}


def test_the_same_key_in_both_variables_is_accepted() -> None:
    environ = {SDK_KEY_VARIABLE: "e2b_test_key_not_real", SYN_KEY_VARIABLE: "e2b_test_key_not_real"}
    bridge_sdk_key(environ)
    assert environ[SDK_KEY_VARIABLE] == "e2b_test_key_not_real"


def test_two_different_keys_are_refused_without_printing_either() -> None:
    environ = {SDK_KEY_VARIABLE: "sdk_test_key_not_real", SYN_KEY_VARIABLE: "syn_test_not_real"}
    with pytest.raises(TemplateBuildError, match="different keys") as refused:
        bridge_sdk_key(environ)
    assert "not_real" not in str(refused.value)


def test_no_key_at_all_refuses_before_building() -> None:
    with pytest.raises(TemplateBuildError, match=SYN_KEY_VARIABLE):
        bridge_sdk_key({})
