"""Unit tests for ClaudePluginRef parsing and identity (issue #726)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.claude_plugin_ref import ClaudePluginRef

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


class TestGitHubShorthand:
    def test_org_repo_at_semver(self) -> None:
        ref = ClaudePluginRef.model_validate("syntropic137/software-leverage-points@5.0.7")
        assert ref.name == "software-leverage-points"
        assert ref.source_url == "https://github.com/syntropic137/software-leverage-points"
        assert ref.version == "5.0.7"
        assert ref.name_overridden is False

    def test_obra_superpowers(self) -> None:
        ref = ClaudePluginRef.model_validate("obra/superpowers@2.1.0")
        assert ref.source_url == "https://github.com/obra/superpowers"
        assert ref.version == "2.1.0"

    def test_branch_as_version(self) -> None:
        ref = ClaudePluginRef.model_validate("foo/bar@feature/branch")
        # version captures the rest of the string after the FIRST @ in shorthand form.
        assert ref.version == "feature/branch"


class TestFullURL:
    def test_https_with_git_suffix(self) -> None:
        ref = ClaudePluginRef.model_validate("https://gitlab.com/foo/bar.git@1.2.0")
        assert ref.source_url == "https://gitlab.com/foo/bar.git"
        assert ref.version == "1.2.0"
        assert ref.name == "bar"

    def test_git_ssh(self) -> None:
        ref = ClaudePluginRef.model_validate("git+ssh://git@host/baz.git@2.0.0")
        assert ref.source_url == "git+ssh://git@host/baz.git"
        assert ref.version == "2.0.0"
        assert ref.name == "baz"

    def test_ssh_shorthand_splits_on_last_at(self) -> None:
        # git@host:org/repo.git@v1 - the prefix's @ must NOT be misread as the version delimiter.
        ref = ClaudePluginRef.model_validate("git@github.com:org/repo.git@v1.0.0")
        assert ref.source_url == "git@github.com:org/repo.git"
        assert ref.version == "v1.0.0"
        assert ref.name == "repo"


class TestVerboseDict:
    def test_with_explicit_name(self) -> None:
        ref = ClaudePluginRef.model_validate(
            {
                "source": "github.com/syntropic137/software-leverage-points",
                "version": "5.0.7",
                "name": "leverage-points",
            }
        )
        assert ref.name == "leverage-points"
        assert ref.name_overridden is True
        assert ref.source_url == "https://github.com/syntropic137/software-leverage-points"
        assert ref.version == "5.0.7"

    def test_without_name_uses_basename(self) -> None:
        ref = ClaudePluginRef.model_validate(
            {
                "source": "github.com/syntropic137/software-leverage-points",
                "version": "5.0.7",
            }
        )
        assert ref.name == "software-leverage-points"
        assert ref.name_overridden is False

    def test_source_url_alias(self) -> None:
        ref = ClaudePluginRef.model_validate(
            {"source_url": "https://example.com/foo.git", "version": "1.0"}
        )
        assert ref.source_url == "https://example.com/foo.git"
        assert ref.name == "foo"


class TestRejection:
    def test_at_latest(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            ClaudePluginRef.model_validate("foo/bar@latest")

    def test_at_latest_verbose(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            ClaudePluginRef.model_validate({"source": "foo/bar", "version": "latest"})

    def test_empty_version_string(self) -> None:
        with pytest.raises(ValidationError):
            ClaudePluginRef.model_validate("foo/bar@")

    def test_empty_version_dict(self) -> None:
        with pytest.raises(ValidationError):
            ClaudePluginRef.model_validate({"source": "foo/bar", "version": ""})

    def test_empty_source(self) -> None:
        with pytest.raises(ValidationError):
            ClaudePluginRef.model_validate({"source": "", "version": "1.0"})

    def test_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            ClaudePluginRef.model_validate("")

    def test_unrecognized_form(self) -> None:
        with pytest.raises(ValidationError):
            ClaudePluginRef.model_validate("just-a-bare-string")


class TestIdentity:
    def test_equal_when_source_version_and_name_all_match(self) -> None:
        a = ClaudePluginRef.model_validate("syntropic137/slp@5.0.7")
        b = ClaudePluginRef.model_validate(
            {
                "source": "github.com/syntropic137/slp",
                "version": "5.0.7",
            }
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_set_dedups_across_scopes(self) -> None:
        a = ClaudePluginRef.model_validate("foo/bar@1.0.0")
        b = ClaudePluginRef.model_validate("foo/bar@1.0.0")
        c = ClaudePluginRef.model_validate("foo/bar@2.0.0")
        assert len({a, b, c}) == 2

    def test_not_equal_when_version_differs(self) -> None:
        a = ClaudePluginRef.model_validate("foo/bar@1.0.0")
        b = ClaudePluginRef.model_validate("foo/bar@1.0.1")
        assert a != b

    def test_not_equal_when_only_name_differs(self) -> None:
        # WHY: lock projection keys on (source_url, version, name); two refs to
        # the same repo+version registered under different display names are
        # distinct lock entries, so the set must preserve both. Regression test
        # for the prior bug where equality ignored ``name``.
        a = ClaudePluginRef.model_validate(
            {
                "source": "github.com/foo/bar",
                "version": "1.0.0",
                "name": "alpha",
            }
        )
        b = ClaudePluginRef.model_validate(
            {
                "source": "github.com/foo/bar",
                "version": "1.0.0",
                "name": "beta",
            }
        )
        assert a != b
        assert hash(a) != hash(b)
        assert len({a, b}) == 2


class TestJsonSchema:
    """The published JSON schema must cover every accepted input form.

    Regression for PR #764 review: the generated workflow.schema.json only
    allowed the canonical object shape, so editors/CI validating YAML against
    it rejected the documented string shorthand examples.
    """

    def test_schema_is_anyof_string_or_object(self) -> None:
        schema = ClaudePluginRef.model_json_schema()
        forms = schema["anyOf"]
        types = [form["type"] for form in forms]
        assert types == ["string", "object"]

    def test_string_form_allows_shorthand_examples(self) -> None:
        schema = ClaudePluginRef.model_json_schema()
        string_form = schema["anyOf"][0]
        assert string_form["type"] == "string"
        assert string_form["minLength"] == 1

    def test_object_form_matches_verbose_mapping(self) -> None:
        schema = ClaudePluginRef.model_json_schema()
        object_form = schema["anyOf"][1]
        assert object_form["required"] == ["version"]
        # Either ``source`` or ``source_url`` satisfies the mapping form.
        assert {"required": ["source"]} in object_form["anyOf"]
        assert {"required": ["source_url"]} in object_form["anyOf"]
        assert set(object_form["properties"]) == {
            "source",
            "source_url",
            "version",
            "name",
            "name_overridden",
        }
