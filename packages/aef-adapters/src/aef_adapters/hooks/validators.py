"""Validator registry for security validation of tool operations.

This module provides a registry of validators that can be used to
check tool inputs before execution. Validators are loaded from
the agentic-primitives library.

Example:
    from aef_adapters.hooks import ValidatorRegistry

    registry = ValidatorRegistry()

    # Validate a bash command
    result = registry.validate("Bash", {"command": "ls -la"})
    if not result.safe:
        print(f"Blocked: {result.reason}")

    # Validate a file operation
    result = registry.validate("Write", {"file_path": "/etc/passwd"})
    if not result.safe:
        print(f"Blocked: {result.reason}")
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Protocol

# Type for validator function
ValidatorFunc = Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]


class Validator(Protocol):
    """Protocol for validator modules."""

    def validate(
        self, tool_input: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate tool input.

        Args:
            tool_input: The tool input to validate.
            context: Optional context information.

        Returns:
            Dict with 'safe' (bool), 'reason' (str|None), 'metadata' (dict|None).
        """
        ...


@dataclass(frozen=True)
class ValidationResult:
    """Result from a validation operation.

    Immutable to ensure validation results are not accidentally modified.
    """

    safe: bool
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    validator_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], validator_name: str | None = None) -> ValidationResult:
        """Create ValidationResult from a validator response dict.

        Args:
            data: Dict with 'safe', 'reason', 'metadata' keys.
            validator_name: Name of the validator that produced this result.

        Returns:
            ValidationResult instance.
        """
        return cls(
            safe=bool(data.get("safe", True)),
            reason=data.get("reason"),
            metadata=data.get("metadata"),
            validator_name=validator_name,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"safe": self.safe}
        if self.reason is not None:
            result["reason"] = self.reason
        if self.metadata is not None:
            result["metadata"] = self.metadata
        if self.validator_name is not None:
            result["validator_name"] = self.validator_name
        return result


def _get_validators_dir() -> Path:
    """Get the path to the validators directory in agentic-primitives.

    Returns:
        Path to the validators directory.

    Raises:
        FileNotFoundError: If validators directory not found.
    """
    # Try relative to this file first (works in dev)
    # The structure is:
    # agentic-engineering-framework/
    # ├── lib/agentic-primitives/primitives/v1/hooks/validators/
    # └── packages/aef-adapters/src/aef_adapters/hooks/validators.py (this file)

    current_file = Path(__file__).resolve()
    # Go up to agentic-engineering-framework root
    # validators.py -> hooks/ -> aef_adapters/ -> src/ -> aef-adapters/ -> packages/ -> aef-root
    aef_root = current_file.parent.parent.parent.parent.parent.parent

    validators_path = (
        aef_root / "lib" / "agentic-primitives" / "primitives" / "v1" / "hooks" / "validators"
    )

    if validators_path.exists():
        return validators_path

    # Fallback: try from environment variable
    import os

    env_path = os.getenv("AGENTIC_PRIMITIVES_VALIDATORS_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    raise FileNotFoundError(
        f"Validators directory not found at {validators_path}. "
        "Ensure agentic-primitives submodule is initialized."
    )


def _load_validator(validator_path: str) -> ValidatorFunc:
    """Dynamically load a validator module.

    Args:
        validator_path: Dotted path like 'security.bash' or 'prompt.pii'.

    Returns:
        The validate function from the module.

    Raises:
        ImportError: If validator module not found.
        AttributeError: If module doesn't have validate function.
    """
    validators_dir = _get_validators_dir()

    # Convert dotted path to file path (e.g., 'security.bash' -> 'security/bash.py')
    parts = validator_path.split(".")
    module_path = validators_dir / "/".join(parts[:-1]) / f"{parts[-1]}.py"

    if not module_path.exists():
        raise ImportError(f"Validator module not found: {module_path}")

    # Load the module dynamically
    spec = spec_from_file_location(f"validator_{validator_path}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load validator: {validator_path}")

    module = module_from_spec(spec)
    sys.modules[f"validator_{validator_path}"] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "validate"):
        raise AttributeError(f"Validator {validator_path} has no validate function")

    return module.validate  # type: ignore[no-any-return]


@dataclass
class ValidatorRegistry:
    """Registry of validators for tool validation.

    Maps tool names to their validator paths and provides methods
    to validate tool inputs.

    Attributes:
        tool_validators: Map of tool names to validator paths.
        prompt_validators: List of validators for user prompts.
        _loaded_validators: Cache of loaded validator functions.
    """

    # Tool validators map tool names to list of validator paths
    tool_validators: dict[str, list[str]] = field(
        default_factory=lambda: {
            "Bash": ["security.bash"],
            "Write": ["security.file"],
            "Edit": ["security.file"],
            "Read": ["security.file"],
            "MultiEdit": ["security.file"],
        }
    )

    # Prompt validators (run on user input)
    prompt_validators: list[str] = field(default_factory=lambda: ["prompt.pii"])

    # Cache of loaded validators
    _loaded_validators: dict[str, ValidatorFunc] = field(default_factory=dict, repr=False)

    def _get_validator(self, validator_path: str) -> ValidatorFunc:
        """Get a validator, loading it if necessary.

        Args:
            validator_path: Dotted path like 'security.bash'.

        Returns:
            The validate function.
        """
        if validator_path not in self._loaded_validators:
            self._loaded_validators[validator_path] = _load_validator(validator_path)
        return self._loaded_validators[validator_path]

    def validate(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate a tool input.

        Runs all validators registered for the tool. If any validator
        returns safe=False, returns that result immediately.

        Args:
            tool_name: Name of the tool (e.g., 'Bash', 'Write').
            tool_input: The tool input to validate.
            context: Optional context information.

        Returns:
            ValidationResult with combined validation outcome.
        """
        validators = self.tool_validators.get(tool_name, [])

        if not validators:
            # No validators for this tool - allow
            return ValidationResult(safe=True)

        for validator_path in validators:
            try:
                validator = self._get_validator(validator_path)
                result = validator(tool_input, context)
                validation = ValidationResult.from_dict(result, validator_path)

                if not validation.safe:
                    return validation

            except Exception as e:
                # Validator failed to load or execute - log but allow
                # This is fail-open behavior to avoid blocking agents
                # TODO: Add logging for validator errors
                return ValidationResult(
                    safe=True,
                    reason=None,
                    metadata={"validator_error": str(e), "validator": validator_path},
                )

        return ValidationResult(safe=True)

    def validate_prompt(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate a user prompt.

        Runs all prompt validators. If any returns safe=False,
        returns that result immediately.

        Args:
            prompt: The user prompt text.
            context: Optional context information.

        Returns:
            ValidationResult with combined validation outcome.
        """
        tool_input = {"prompt": prompt}

        for validator_path in self.prompt_validators:
            try:
                validator = self._get_validator(validator_path)
                result = validator(tool_input, context)
                validation = ValidationResult.from_dict(result, validator_path)

                if not validation.safe:
                    return validation

            except Exception as e:
                # Validator failed - log but allow
                return ValidationResult(
                    safe=True,
                    reason=None,
                    metadata={"validator_error": str(e), "validator": validator_path},
                )

        return ValidationResult(safe=True)

    def add_tool_validator(self, tool_name: str, validator_path: str) -> None:
        """Register a validator for a tool.

        Args:
            tool_name: Name of the tool.
            validator_path: Dotted path to validator (e.g., 'security.custom').
        """
        if tool_name not in self.tool_validators:
            self.tool_validators[tool_name] = []
        if validator_path not in self.tool_validators[tool_name]:
            self.tool_validators[tool_name].append(validator_path)

    def add_prompt_validator(self, validator_path: str) -> None:
        """Register a prompt validator.

        Args:
            validator_path: Dotted path to validator (e.g., 'prompt.custom').
        """
        if validator_path not in self.prompt_validators:
            self.prompt_validators.append(validator_path)
