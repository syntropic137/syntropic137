"""Tests for SkillRef parsing (issue #772)."""

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
    expand_skill_entry,
)


class TestShorthandForm:
    def test_org_repo_skill_at_version(self) -> None:
        ref = SkillRef.model_validate("anthropics/skills/frontend-design@v1.2.0")
        assert ref.skill_name == "frontend-design"
        assert ref.source_url == "https://github.com/anthropics/skills"
        assert ref.version == "v1.2.0"
        assert ref.name_overridden is False

    def test_two_segment_shorthand_rejected(self) -> None:
        # org/repo@version is ambiguous for skills (which skill in the repo?);
        # require the third segment or the verbose form.
        with pytest.raises(ValidationError, match="org/repo/skill-name@version"):
            SkillRef.model_validate("anthropics/skills@v1.2.0")

    def test_latest_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate("anthropics/skills/frontend-design@latest")

    def test_domain_qualified_shorthand_rejected(self) -> None:
        # A hostname-looking first segment is not GitHub shorthand; require the
        # explicit URL or verbose form instead of silently mis-parsing.
        with pytest.raises(ValidationError, match="looks like a host"):
            SkillRef.model_validate("gitlab.example.com/org/repo@v1")


class TestUrlForm:
    def test_url_at_version_uses_basename_as_skill_name(self) -> None:
        ref = SkillRef.model_validate("https://github.com/acme/tdd-skill@v2.0.0")
        assert ref.skill_name == "tdd-skill"
        assert ref.source_url == "https://github.com/acme/tdd-skill"
        assert ref.version == "v2.0.0"

    def test_missing_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing '@<version>'"):
            SkillRef.model_validate("https://github.com/acme/tdd-skill")

    def test_slash_in_version_rejected_with_verbose_form_hint(self) -> None:
        # A branch pin like 'feature/foo' cannot be expressed unambiguously
        # in the compact '<url>@<version>' string form; the error should
        # point at the verbose mapping form rather than claim the version is
        # simply missing.
        with pytest.raises(ValidationError, match="verbose mapping form"):
            SkillRef.model_validate("https://github.com/acme/tdd-skill@feature/foo")


class TestVerboseForm:
    def test_single_name(self) -> None:
        ref = SkillRef.model_validate(
            {"source": "github.com/acme/agent-skills", "version": "v2.0.0", "name": "code-review"}
        )
        assert ref.skill_name == "code-review"
        assert ref.source_url == "https://github.com/acme/agent-skills"
        assert ref.name_overridden is True

    def test_slash_containing_version_accepted(self) -> None:
        # The verbose mapping form has no url/version ambiguity, so branch
        # pins like 'feature/foo' parse cleanly here even though they are
        # rejected in the compact '<url>@<version>' string form.
        ref = SkillRef.model_validate(
            {
                "source": "https://github.com/acme/agent-skills",
                "version": "feature/foo",
                "name": "code-review",
            }
        )
        assert ref.version == "feature/foo"


class TestExpandSkillEntry:
    def test_names_list_expands(self) -> None:
        refs = expand_skill_entry(
            {
                "source": "https://github.com/acme/agent-skills",
                "version": "v2.0.0",
                "names": ["code-review", "tdd-workflow"],
            }
        )
        assert [r.skill_name for r in refs] == ["code-review", "tdd-workflow"]
        assert all(r.source_url == "https://github.com/acme/agent-skills" for r in refs)
        assert all(r.version == "v2.0.0" for r in refs)

    def test_string_entry_yields_single_ref(self) -> None:
        refs = expand_skill_entry("anthropics/skills/frontend-design@v1.2.0")
        assert len(refs) == 1
        assert refs[0].skill_name == "frontend-design"

    def test_empty_names_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="'names' must be a non-empty list"):
            expand_skill_entry({"source": "github.com/a/b", "version": "v1", "names": []})


class TestIdentity:
    def test_eq_and_hash_by_source_version_name(self) -> None:
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate(
            {"source": "https://github.com/acme/skills", "version": "v1", "name": "foo"}
        )
        assert a == b
        assert hash(a) == hash(b)
