"""Tests for SkillRef parsing (issue #772)."""

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
    expand_skill_entry,
)


@pytest.mark.unit
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


@pytest.mark.unit
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

    def test_ambiguous_double_at_rejected(self) -> None:
        # Splitting on the LAST '@' would silently produce source_url
        # '.../skills@release' + version '2026' -- a corrupted pin -- if a
        # git ref itself is named 'release@2026'. Must be rejected instead.
        with pytest.raises(ValidationError, match="ambiguous '@'"):
            SkillRef.model_validate("https://github.com/org/skills@release@2026")

    def test_ssh_form_still_parses(self) -> None:
        # The ssh user-info '@' (git@host) is the one legitimate '@' before
        # the version delimiter and must continue to parse.
        ref = SkillRef.model_validate("git@github.com:org/skills@v1")
        assert ref.source_url == "git@github.com:org/skills"
        assert ref.version == "v1"

    def test_git_ssh_prefixed_form_still_parses(self) -> None:
        ref = SkillRef.model_validate("git+ssh://git@github.com/org/skills@v1")
        assert ref.source_url == "git+ssh://git@github.com/org/skills"
        assert ref.version == "v1"


@pytest.mark.unit
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

    def test_at_containing_version_accepted(self) -> None:
        # The verbose mapping form splits source and version explicitly, so
        # a ref name literally containing '@' (e.g. 'release@2026') parses
        # cleanly here even though the compact string form must reject it.
        ref = SkillRef.model_validate(
            {
                "source": "https://github.com/org/skills",
                "version": "release@2026",
                "name": "code-review",
            }
        )
        assert ref.version == "release@2026"


@pytest.mark.unit
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


@pytest.mark.unit
class TestIdentity:
    def test_eq_and_hash_by_source_version_name(self) -> None:
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate(
            {"source": "https://github.com/acme/skills", "version": "v1", "name": "foo"}
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_differing_version_is_a_different_identity(self) -> None:
        # The merge in SkillResolutionService keys on this equality, so a
        # version difference MUST NOT collapse two refs into one.
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate("acme/skills/foo@v2")
        assert a != b
        assert len({a, b}) == 2

    def test_differing_name_from_one_source_is_a_different_identity(self) -> None:
        # One repo+tag publishing several skills must produce several entries.
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate("acme/skills/bar@v1")
        assert a != b
        assert len({a, b}) == 2

    def test_differing_source_with_same_name_and_version_is_different(self) -> None:
        a = SkillRef.model_validate("upstream/skills/foo@v1")
        b = SkillRef.model_validate("fork/skills/foo@v1")
        assert a != b
        assert len({a, b}) == 2

    def test_name_overridden_is_not_part_of_identity(self) -> None:
        # name_overridden records HOW the name was derived, not WHICH skill
        # this is; letting it split identity would double-install one skill.
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate(
            {"source": "https://github.com/acme/skills", "version": "v1", "name": "foo"}
        )
        assert a.name_overridden is False
        assert b.name_overridden is True
        assert a == b
        assert hash(a) == hash(b)

    def test_comparison_against_a_non_skillref_is_not_equal(self) -> None:
        ref = SkillRef.model_validate("acme/skills/foo@v1")
        assert ref != "acme/skills/foo@v1"
        assert ref != object()


@pytest.mark.unit
class TestLatestRejection:
    """@latest defeats the lockfile, so it must be rejected in EVERY input form.

    The shorthand case is covered above; these pin the other doors into the
    same validator, including the normalization it applies before comparing.
    """

    def test_latest_rejected_in_url_string_form(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate("https://github.com/acme/tdd-skill@latest")

    def test_latest_rejected_in_verbose_form(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate({"source": "github.com/acme/skills", "version": "latest"})

    def test_latest_rejected_case_insensitively(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate("acme/skills/foo@LATEST")

    def test_latest_rejected_with_surrounding_whitespace(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate({"source": "github.com/acme/skills", "version": " Latest "})

    def test_latest_rejected_via_expand_skill_entry(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            expand_skill_entry(
                {"source": "github.com/a/b", "version": "latest", "names": ["x", "y"]}
            )

    def test_version_merely_containing_latest_is_accepted(self) -> None:
        # Only the exact token is banned; 'v1-latest-stable' is a real pin.
        ref = SkillRef.model_validate("acme/skills/foo@v1-latest-stable")
        assert ref.version == "v1-latest-stable"


@pytest.mark.unit
class TestMalformedInput:
    """Inputs that must fail loudly rather than parse into a wrong identity."""

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            SkillRef.model_validate("")

    def test_whitespace_only_string_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            SkillRef.model_validate("   ")

    def test_bare_word_rejected_as_unrecognized_form(self) -> None:
        with pytest.raises(ValidationError, match="not a recognized form"):
            SkillRef.model_validate("frontend-design")

    def test_empty_version_after_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty version"):
            SkillRef.model_validate("https://github.com/acme/tdd-skill@")

    def test_second_url_in_version_position_rejected(self) -> None:
        # rfind('@') on 'https://a/b@https://c' would otherwise yield a
        # "version" that is itself a URL.
        with pytest.raises(ValidationError, match="missing '@<version>'"):
            SkillRef.model_validate("https://github.com/a/b@https://github.com/c/d")

    def test_verbose_form_without_source_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires non-empty 'source'"):
            SkillRef.model_validate({"source": "", "version": "v1"})

    def test_verbose_form_without_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires non-empty 'version'"):
            SkillRef.model_validate({"source": "github.com/a/b"})

    def test_unknown_field_rejected(self) -> None:
        # extra="forbid": a typo'd key must not be silently dropped.
        with pytest.raises(ValidationError):
            SkillRef.model_validate(
                {
                    "skill_name": "foo",
                    "source_url": "https://github.com/a/b",
                    "version": "v1",
                    "sha": "deadbeef",
                }
            )

    def test_ref_is_frozen(self) -> None:
        ref = SkillRef.model_validate("acme/skills/foo@v1")
        with pytest.raises(ValidationError):
            ref.version = "v2"  # type: ignore[misc]


@pytest.mark.unit
class TestNameDerivation:
    """The skill name decides the on-disk install path, so derivation is load-bearing."""

    def test_git_suffix_stripped_from_url_basename(self) -> None:
        ref = SkillRef.model_validate("https://github.com/acme/tdd-skill.git@v1")
        assert ref.skill_name == "tdd-skill"
        assert ref.source_url == "https://github.com/acme/tdd-skill.git"

    def test_trailing_slash_ignored_by_url_basename(self) -> None:
        ref = SkillRef.model_validate(
            {"source": "https://github.com/acme/tdd-skill/", "version": "v1"}
        )
        assert ref.skill_name == "tdd-skill"

    def test_ssh_form_basename_taken_after_the_colon(self) -> None:
        ref = SkillRef.model_validate("git@github.com:org/skills@v1")
        assert ref.skill_name == "skills"

    def test_verbose_form_without_name_derives_from_source_and_is_not_overridden(self) -> None:
        ref = SkillRef.model_validate({"source": "github.com/acme/tdd-skill", "version": "v1"})
        assert ref.skill_name == "tdd-skill"
        assert ref.name_overridden is False

    def test_source_url_alias_accepted_in_verbose_form(self) -> None:
        ref = SkillRef.model_validate({"source_url": "github.com/acme/tdd-skill", "version": "v1"})
        assert ref.source_url == "https://github.com/acme/tdd-skill"
        assert ref.skill_name == "tdd-skill"

    def test_surrounding_whitespace_stripped_from_string_form(self) -> None:
        ref = SkillRef.model_validate("  acme/skills/foo@v1  ")
        assert ref.skill_name == "foo"
        assert ref.version == "v1"

    def test_bare_host_source_expanded_to_https(self) -> None:
        ref = SkillRef.model_validate({"source": "gitlab.example.com/org/repo", "version": "v1"})
        assert ref.source_url == "https://gitlab.example.com/org/repo"


@pytest.mark.unit
class TestRoundTrip:
    def test_model_dump_revalidates_to_an_equal_ref(self) -> None:
        # The before-validator must recognize an already-canonical dump and
        # not try to re-parse it as the verbose YAML form.
        original = SkillRef.model_validate("acme/skills/foo@v1")
        reparsed = SkillRef.model_validate(original.model_dump())
        assert reparsed == original
        assert reparsed.skill_name == "foo"
        assert reparsed.source_url == "https://github.com/acme/skills"
        assert reparsed.name_overridden is False

    def test_expand_skill_entry_names_override_a_base_name_key(self) -> None:
        refs = expand_skill_entry(
            {
                "source": "https://github.com/acme/agent-skills",
                "version": "v2.0.0",
                "name": "ignored",
                "names": ["alpha", "beta"],
            }
        )
        assert [r.skill_name for r in refs] == ["alpha", "beta"]
        assert all(r.name_overridden for r in refs)

    def test_expand_skill_entry_rejects_non_list_names(self) -> None:
        with pytest.raises(ValueError, match="'names' must be a non-empty list"):
            expand_skill_entry({"source": "github.com/a/b", "version": "v1", "names": "alpha"})
