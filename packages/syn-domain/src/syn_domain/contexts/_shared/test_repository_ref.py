"""Tests for RepositoryRef value object."""

from __future__ import annotations

import pytest

from syn_domain.contexts._shared.repository_ref import RepositoryRef


class TestFromSlug:
    def test_valid_slug(self) -> None:
        ref = RepositoryRef.from_slug("syntropic137/my-project")
        assert ref.owner == "syntropic137"
        assert ref.name == "my-project"

    def test_slug_with_dots(self) -> None:
        ref = RepositoryRef.from_slug("org.name/repo.name")
        assert ref.owner == "org.name"
        assert ref.name == "repo.name"

    def test_slug_with_underscores(self) -> None:
        ref = RepositoryRef.from_slug("my_org/my_repo")
        assert ref.owner == "my_org"
        assert ref.name == "my_repo"

    def test_invalid_slug_no_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository slug"):
            RepositoryRef.from_slug("just-a-name")

    def test_invalid_slug_too_many_slashes(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository slug"):
            RepositoryRef.from_slug("a/b/c")

    def test_invalid_slug_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository slug"):
            RepositoryRef.from_slug("")

    def test_invalid_slug_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository slug"):
            RepositoryRef.from_slug("https://github.com/owner/repo")


class TestFromUrl:
    def test_valid_https_url(self) -> None:
        ref = RepositoryRef.from_url("https://github.com/syntropic137/my-project")
        assert ref.owner == "syntropic137"
        assert ref.name == "my-project"

    def test_url_with_trailing_slash(self) -> None:
        ref = RepositoryRef.from_url("https://github.com/owner/repo/")
        assert ref.owner == "owner"
        assert ref.name == "repo"

    def test_url_with_dot_git(self) -> None:
        ref = RepositoryRef.from_url("https://github.com/owner/repo.git")
        assert ref.owner == "owner"
        assert ref.name == "repo"

    def test_invalid_url_wrong_host(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository URL"):
            RepositoryRef.from_url("https://gitlab.com/owner/repo")

    def test_invalid_url_no_repo(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository URL"):
            RepositoryRef.from_url("https://github.com/owner")

    def test_invalid_url_not_url(self) -> None:
        with pytest.raises(ValueError, match="Invalid repository URL"):
            RepositoryRef.from_url("owner/repo")


class TestParse:
    def test_parse_slug(self) -> None:
        ref = RepositoryRef.parse("owner/repo")
        assert ref.slug == "owner/repo"

    def test_parse_url(self) -> None:
        ref = RepositoryRef.parse("https://github.com/owner/repo")
        assert ref.slug == "owner/repo"

    def test_parse_http_url(self) -> None:
        ref = RepositoryRef.parse("http://github.com/owner/repo")
        assert ref.slug == "owner/repo"

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError):
            RepositoryRef.parse("not-valid")


class TestProperties:
    def test_slug_property(self) -> None:
        ref = RepositoryRef(owner="syntropic137", name="my-project")
        assert ref.slug == "syntropic137/my-project"

    def test_https_url_property(self) -> None:
        ref = RepositoryRef(owner="syntropic137", name="my-project")
        assert ref.https_url == "https://github.com/syntropic137/my-project"

    def test_str(self) -> None:
        ref = RepositoryRef(owner="owner", name="repo")
        assert str(ref) == "owner/repo"

    def test_repr(self) -> None:
        ref = RepositoryRef(owner="owner", name="repo")
        assert repr(ref) == "RepositoryRef('owner/repo')"


class TestImmutability:
    def test_frozen(self) -> None:
        ref = RepositoryRef(owner="owner", name="repo")
        with pytest.raises(AttributeError):
            ref.owner = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = RepositoryRef.from_slug("owner/repo")
        b = RepositoryRef.from_url("https://github.com/owner/repo")
        assert a == b

    def test_hash(self) -> None:
        a = RepositoryRef.from_slug("owner/repo")
        b = RepositoryRef.from_url("https://github.com/owner/repo")
        assert hash(a) == hash(b)
        assert len({a, b}) == 1


class TestValidation:
    def test_empty_owner(self) -> None:
        with pytest.raises(ValueError, match="owner cannot be empty"):
            RepositoryRef(owner="", name="repo")

    def test_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            RepositoryRef(owner="owner", name="")


class TestRoundTrip:
    """Verify slug -> RepositoryRef -> URL -> RepositoryRef -> slug roundtrip."""

    def test_slug_to_url_roundtrip(self) -> None:
        original = "syntropic137/my-project"
        ref1 = RepositoryRef.from_slug(original)
        ref2 = RepositoryRef.from_url(ref1.https_url)
        assert ref2.slug == original

    def test_url_to_slug_roundtrip(self) -> None:
        original = "https://github.com/syntropic137/my-project"
        ref1 = RepositoryRef.from_url(original)
        ref2 = RepositoryRef.from_slug(ref1.slug)
        assert ref2.https_url == original
