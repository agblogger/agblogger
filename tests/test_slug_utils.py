"""Tests for slug utility functions."""

from __future__ import annotations

from backend.utils.slug import file_path_to_slug, resolve_slug_candidates


class TestFilePathToSlug:
    """Tests for file_path_to_slug conversion."""

    def test_directory_backed_post(self) -> None:
        assert file_path_to_slug("posts/my-post/index.md") == "my-post"

    def test_flat_file_post(self) -> None:
        assert file_path_to_slug("posts/hello.md") == "hello.md"

    def test_bare_slug_is_idempotent(self) -> None:
        assert file_path_to_slug("my-post") == "my-post"

    def test_posts_prefix_with_trailing_slash(self) -> None:
        assert file_path_to_slug("posts/my-post/") == "my-post"

    def test_slug_with_hyphens(self) -> None:
        assert file_path_to_slug("posts/my-long-post-title/index.md") == "my-long-post-title"

    def test_flat_file_with_hyphens(self) -> None:
        assert file_path_to_slug("posts/another-post.md") == "another-post.md"

    def test_bare_slug_with_hyphens_is_idempotent(self) -> None:
        assert file_path_to_slug("some-bare-slug") == "some-bare-slug"

    def test_directory_backed_does_not_keep_index(self) -> None:
        """Regression: must strip /index.md entirely, not leave 'my-post/index'."""
        result = file_path_to_slug("posts/my-post/index.md")
        assert "/" not in result
        assert "index" not in result


class TestFilePathToSlugRegressions:
    """Regression tests covering bugs found in crosspost and symlink resolution."""

    def test_directory_backed_post_does_not_produce_index_in_slug(self) -> None:
        """Regression: crosspost_service was producing 'my-post/index' instead of 'my-post'.

        Old code stripped posts/ prefix and .md suffix but did NOT handle /index.md,
        leaving a slash in the slug which breaks crosspost URLs.
        """
        result = file_path_to_slug("posts/my-post/index.md")
        assert result == "my-post"
        assert "index" not in result
        assert "/" not in result

    def test_crosspost_url_with_directory_backed_post(self) -> None:
        """The slug produced by file_path_to_slug matches what a crosspost URL needs."""
        site_url = "https://example.com"
        post_path = "posts/my-first-post/index.md"
        slug = file_path_to_slug(post_path)
        post_url = f"{site_url.rstrip('/')}/post/{slug}"
        assert post_url == "https://example.com/post/my-first-post"

    def test_crosspost_url_with_flat_file_post_preserves_md_suffix(self) -> None:
        site_url = "https://example.com"
        post_path = "posts/hello.md"
        slug = file_path_to_slug(post_path)
        post_url = f"{site_url.rstrip('/')}/post/{slug}"
        assert post_url == "https://example.com/post/hello.md"


class TestResolveSlugCandidates:
    """Tests for resolve_slug_candidates path expansion."""

    def test_returns_tuple_of_one_candidate(self) -> None:
        candidates = resolve_slug_candidates("my-post")
        assert len(candidates) == 1

    def test_directory_backed_candidate(self) -> None:
        candidates = resolve_slug_candidates("my-post")
        assert candidates[0] == "posts/my-post/index.md"

    def test_slug_with_hyphens(self) -> None:
        candidates = resolve_slug_candidates("hello-world")
        assert candidates == ("posts/hello-world/index.md",)

    def test_returns_tuple_type(self) -> None:
        result = resolve_slug_candidates("my-post")
        assert isinstance(result, tuple)
