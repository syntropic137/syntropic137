"""Typed conflict errors for the WorkflowTemplate aggregate.

WHY (issue #822): install/upsert has to distinguish "you already have this
exact thing" from "you have this version but the bytes changed underneath
you". Callers map these to HTTP 409 with a domain message instead of string
matching on an event-store internal.
"""

from __future__ import annotations


class WorkflowTemplateConflictError(Exception):
    """Base for conflicts that mean the caller's intent collides with stored state.

    Maps to HTTP 409. Never carries event-store wording.
    """


class WorkflowTemplateVersionAlreadyInstalledError(WorkflowTemplateConflictError):
    """The requested version is already installed and force was not set."""

    def __init__(self, workflow_id: str, version: str) -> None:
        self.workflow_id = workflow_id
        self.version = version
        super().__init__(
            f"Workflow '{workflow_id}' version {version} is already installed. "
            f"Pass --force to reinstall it."
        )


class WorkflowTemplateDigestMismatchError(WorkflowTemplateConflictError):
    """Same version resolved to different source content than what is installed.

    WHY: this is the supply-chain republish signature. A version check alone
    sails straight past it, so it refuses loudly rather than no-opping.
    """

    def __init__(
        self,
        workflow_id: str,
        version: str,
        installed_digest: str,
        incoming_digest: str,
    ) -> None:
        self.workflow_id = workflow_id
        self.version = version
        self.installed_digest = installed_digest
        self.incoming_digest = incoming_digest
        super().__init__(
            f"Workflow '{workflow_id}' version {version} resolves to a different source "
            f"than the installed copy (installed {installed_digest}, incoming "
            f"{incoming_digest}). The publisher may have replaced an existing version. "
            f"Review the change, then pass --force if it is expected."
        )


class WorkflowTemplateProvenanceStrippedError(WorkflowTemplateConflictError):
    """An install would erase provenance already recorded on the template.

    WHY: without this, the digest guard is trivially bypassed. Install once at
    0.3.0/aaa111, then install again declaring neither version nor digest: the
    matching-version check does not fire, the update is accepted, and both
    fields are overwritten with None. A republished 0.3.0 then installs
    cleanly, because there is no longer a recorded digest to compare against.

    ``force`` does not bypass this. Force means "overwrite this version on
    purpose", not "drop the evidence".
    """

    def __init__(self, workflow_id: str, field: str, installed_value: str) -> None:
        self.workflow_id = workflow_id
        self.field = field
        self.installed_value = installed_value
        super().__init__(
            f"Workflow '{workflow_id}' is installed with {field} {installed_value}, but this "
            f"install declares no {field}. Refusing to overwrite recorded provenance with "
            f"nothing. Reinstall from a source that declares its {field}."
        )
