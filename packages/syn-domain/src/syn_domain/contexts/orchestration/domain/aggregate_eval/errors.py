"""The rules an Eval refuses to break, one type each (evals plan, #967).

All are ``ValueError`` so the slice handlers turn every one into a
``HandlerResult(success=False)`` the same way the other orchestration slices
do, while a caller that needs to tell them apart can still dispatch on type.
"""

from __future__ import annotations


class EvalRuleError(ValueError):
    """Base for every Eval invariant violation."""


class EvalNotCreatedError(EvalRuleError):
    """A command other than CreateEval reached an aggregate with no stream."""

    def __init__(self) -> None:
        super().__init__("Eval does not exist")


class EvalAlreadyExistsError(EvalRuleError):
    """CreateEval reached an aggregate that already has history."""

    def __init__(self, eval_id: str) -> None:
        super().__init__(f"Eval {eval_id} already exists")


class EvalArchivedError(EvalRuleError):
    """An archived eval refuses edits and freezing. It stays readable."""

    def __init__(self, eval_id: str, action: str) -> None:
        super().__init__(f"Eval {eval_id} is archived and cannot be {action}")


class EvalFrozenError(EvalRuleError):
    """A frozen eval's goal and baseline are fixed. Change them in a new eval."""

    def __init__(self, eval_id: str, fields: list[str]) -> None:
        names = " and ".join(fields)
        super().__init__(
            f"Eval {eval_id} is frozen: its {names} cannot change. "
            "Create a new eval to run a different experiment."
        )


class DuplicateBaselineRepositoryError(EvalRuleError):
    """One repository cannot have two starting commits in the same eval."""

    def __init__(self, slugs: list[str]) -> None:
        super().__init__(
            "each repository may appear once in an eval baseline; repeated: " + ", ".join(slugs)
        )


class EvalRunNotMemberError(EvalRuleError):
    """Only a run currently in the eval can be scored against it."""

    def __init__(self, eval_id: str, execution_id: str) -> None:
        self.eval_id = eval_id
        self.execution_id = execution_id
        super().__init__(f"Execution {execution_id} is not a run of eval {eval_id}")
