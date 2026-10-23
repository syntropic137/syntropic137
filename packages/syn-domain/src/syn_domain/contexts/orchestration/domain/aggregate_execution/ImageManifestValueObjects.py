"""What a phase's workspace image said about itself, as recorded provenance (#1913).

The image manifest is `/opt/agentic/version.json`, read off the running
workspace through the provider's file transfer. It is recorded on
`WorkspaceProvisionedForPhase`, so it survives a restart and a replay; the
live `WorkspaceAggregate` is never saved and is not provenance.

A reading is one of three states, and they are never collapsed into each
other: a manifest that was read, a workspace that has none (every image today,
AgentParadise/agentic-workspace#93), and a read that failed. An absent or
unreadable manifest is never recorded as a manifest with empty fields.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from syn_domain.contexts.orchestration._shared.file_transfer import FileRefusal

IMAGE_MANIFEST_ROOT = "/opt/agentic"
"""The transfer root the manifest lives under, inside every workspace image."""

IMAGE_MANIFEST_FILE = "version.json"
"""The manifest's path relative to `IMAGE_MANIFEST_ROOT`."""


class ImageManifestState(StrEnum):
    """Whether the workspace's image manifest was read."""

    READ = "read"
    #: The workspace has no manifest file. Not an error: no image ships one yet.
    ABSENT = "absent"
    #: The file transfer failed, or the file was not a manifest.
    UNREADABLE = "unreadable"


class ImageManifestContent(BaseModel):
    """The fields of `version.json`, every one required: none is guessed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_version: str
    components: dict[str, str]
    build_commit: str
    built_at: str
    #: Hash of the manifest.yaml used for the build. Not an OCI image digest.
    manifest_digest: str


class ImageManifestReading(BaseModel):
    """One workspace's image manifest, or why there is none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ImageManifestState
    #: Set exactly when `state` is READ.
    manifest: ImageManifestContent | None = None
    #: Why the read failed; set exactly when `state` is UNREADABLE.
    detail: str | None = None
    #: The provider's refusal of the manifest file (a link, a special file,
    #: past a limit), by path and reason. Only on an UNREADABLE reading.
    refusal: FileRefusal | None = None

    @model_validator(mode="after")
    def _state_matches_fields(self) -> Self:
        is_read = self.state is ImageManifestState.READ
        if (self.manifest is not None) != is_read:
            msg = f"a {self.state} image manifest reading carries a manifest only when read"
            raise ValueError(msg)
        if (self.detail is not None) != (self.state is ImageManifestState.UNREADABLE):
            msg = f"a {self.state} image manifest reading carries a detail only when unreadable"
            raise ValueError(msg)
        if self.refusal is not None and self.state is not ImageManifestState.UNREADABLE:
            msg = f"a {self.state} image manifest reading cannot carry a refusal"
            raise ValueError(msg)
        return self

    @classmethod
    def absent(cls) -> ImageManifestReading:
        return cls(state=ImageManifestState.ABSENT)

    @classmethod
    def unreadable(cls, detail: str) -> ImageManifestReading:
        return cls(state=ImageManifestState.UNREADABLE, detail=detail)

    @classmethod
    def refused(cls, refusal: FileRefusal) -> ImageManifestReading:
        """The provider would not read the manifest file: unreadable, never absent."""
        return cls(
            state=ImageManifestState.UNREADABLE,
            detail=f"the provider refused to read {refusal.describe()}",
            refusal=refusal,
        )

    @classmethod
    def from_files(cls, files: list[tuple[str, bytes]]) -> ImageManifestReading:
        """The reading for what a transfer of `IMAGE_MANIFEST_FILE` returned."""
        content = next((data for path, data in files if path == IMAGE_MANIFEST_FILE), None)
        if content is None:
            return cls.absent()
        try:
            manifest = ImageManifestContent.model_validate_json(content)
        except ValidationError as e:
            return cls.unreadable(f"{IMAGE_MANIFEST_FILE} is not an image manifest: {e}")
        return cls(state=ImageManifestState.READ, manifest=manifest)


def read_image_manifest(raw: object) -> ImageManifestReading | None:
    """The reading on a replayed event; None on events written before it existed.

    A stored reading that no longer validates is replayed as UNREADABLE, so it
    stays visible instead of turning into "never recorded".
    """
    if raw is None:
        return None
    if isinstance(raw, ImageManifestReading):
        return raw
    try:
        return ImageManifestReading.model_validate(raw)
    except ValidationError as e:
        return ImageManifestReading.unreadable(f"the recorded reading did not replay: {e}")
