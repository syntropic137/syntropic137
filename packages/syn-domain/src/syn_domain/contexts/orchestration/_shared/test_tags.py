"""Tests for the shared TagSet value object (#967)."""

import pytest
from pydantic import BaseModel, ValidationError

from syn_domain.contexts.orchestration._shared.tags import (
    MAX_TAG_LENGTH,
    MAX_TAGS,
    InvalidTagsError,
    TagSet,
)


class _Carrier(BaseModel):
    tags: TagSet = TagSet()


@pytest.mark.unit
class TestNormalisation:
    def test_trims_lowercases_dedupes_and_sorts(self) -> None:
        assert TagSet([" Nightly ", "nightly", "B", "a"]).values == ("a", "b", "nightly")

    def test_every_allowed_character(self) -> None:
        assert TagSet(["team/a-b_c.1"]).values == ("team/a-b_c.1",)

    def test_equal_after_normalisation(self) -> None:
        assert TagSet(["X", "y"]) == TagSet(["y", "x"])


@pytest.mark.unit
class TestRejection:
    @pytest.mark.parametrize("bad", ["", "   ", "has space", "eval:x", "émoji", "a+b"])
    def test_invalid_tag_is_rejected_not_dropped(self, bad: str) -> None:
        with pytest.raises(InvalidTagsError, match="invalid tag"):
            TagSet(["ok", bad])

    def test_error_names_every_bad_tag(self) -> None:
        with pytest.raises(InvalidTagsError) as exc:
            TagSet(["a b", "c:d"])
        assert "'a b'" in str(exc.value)
        assert "'c:d'" in str(exc.value)

    def test_length_limit(self) -> None:
        TagSet(["x" * MAX_TAG_LENGTH])
        with pytest.raises(InvalidTagsError, match="longer than"):
            TagSet(["x" * (MAX_TAG_LENGTH + 1)])

    def test_count_limit(self) -> None:
        TagSet([f"t{i}" for i in range(MAX_TAGS)])
        with pytest.raises(InvalidTagsError, match=f"at most {MAX_TAGS}"):
            TagSet([f"t{i}" for i in range(MAX_TAGS + 1)])

    def test_count_limit_counts_after_dedupe(self) -> None:
        assert len(TagSet(["a", "A", " a"] * MAX_TAGS)) == 1

    def test_bare_string_is_rejected(self) -> None:
        with pytest.raises(InvalidTagsError, match="list of strings"):
            TagSet("nightly")


@pytest.mark.unit
class TestSetOperations:
    def test_union_normalises_the_other_side(self) -> None:
        assert TagSet(["a"]).union(["B", "a"]).values == ("a", "b")

    def test_union_enforces_the_limit(self) -> None:
        left = TagSet([f"l{i}" for i in range(MAX_TAGS)])
        with pytest.raises(InvalidTagsError, match=f"at most {MAX_TAGS}"):
            left.union(["extra"])

    def test_difference(self) -> None:
        assert TagSet(["a", "b", "c"]).difference(["B", "z"]).values == ("a", "c")

    def test_recorded_does_not_revalidate(self) -> None:
        # A rule tightened later must not stop an old event replaying.
        assert TagSet.recorded(["legacy:tag", "a"]).values == ("a", "legacy:tag")


@pytest.mark.unit
class TestPydantic:
    def test_accepts_a_list_and_normalises(self) -> None:
        assert _Carrier.model_validate({"tags": ["B", "a"]}).tags.values == ("a", "b")

    def test_accepts_a_tagset(self) -> None:
        tags = TagSet(["a"])
        assert _Carrier(tags=tags).tags is tags

    def test_json_round_trip(self) -> None:
        dumped = _Carrier(tags=TagSet(["b", "a"])).model_dump_json()
        assert dumped == '{"tags":["a","b"]}'
        assert _Carrier.model_validate_json(dumped).tags == TagSet(["a", "b"])

    def test_invalid_tag_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="contains characters outside"):
            _Carrier.model_validate({"tags": ["bad tag"]})

    def test_scalar_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            _Carrier.model_validate({"tags": "nightly"})

    def test_json_schema_is_a_string_array(self) -> None:
        schema = _Carrier.model_json_schema()["properties"]["tags"]
        assert schema["type"] == "array"
        assert schema["items"] == {"type": "string"}
