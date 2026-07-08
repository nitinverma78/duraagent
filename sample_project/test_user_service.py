"""Tests for user_service module — 6 pass, 3 fail (exposing the 3 bugs)."""

import pytest
from user_service import User, create_user, find_user_by_name, generate_id, validate_email


# ── PASSING TESTS (happy path) ────────────────────────────────────────

class TestUserCreation:
    """These tests pass."""

    def test_create_user_valid(self):
        user = create_user("Alice", "alice@example.com", [1, 2, 3])
        assert user.name == "Alice"
        assert user.email == "alice@example.com"

    def test_create_user_strips_whitespace(self):
        user = create_user("  Bob  ", "bob@test.com", [1])
        assert user.name == "Bob"

    def test_create_user_empty_name_raises(self):
        with pytest.raises(ValueError, match="Name cannot be empty"):
            create_user("", "test@test.com")

    def test_find_user_case_insensitive(self):
        users = [User(1, "Alice Smith", "a@b.com"), User(2, "Bob Jones", "b@c.com")]
        result = find_user_by_name("alice", users)
        assert len(result) == 1
        assert result[0].name == "Alice Smith"

    def test_find_user_no_match(self):
        users = [User(1, "Alice", "a@b.com")]
        assert find_user_by_name("Charlie", users) == []

    def test_user_to_dict(self):
        user = User(1, "Test", "test@test.com")
        d = user.to_dict()
        assert d == {"user_id": 1, "name": "Test", "email": "test@test.com"}


# ── FAILING TESTS (exposing bugs) ────────────────────────────────────

class TestBugs:
    """These tests FAIL — each one exposes a specific bug."""

    def test_create_user_invalid_email_should_raise(self):
        """BUG: create_user accepts 'not_an_email' without validation."""
        with pytest.raises(ValueError, match="Invalid email"):
            create_user("Alice", "not_an_email", [1, 2])

    def test_find_user_no_sql_injection(self):
        """BUG: find_user_by_name builds an unsafe SQL-like query string."""
        users = [User(1, "Alice", "a@b.com")]
        # The function works, but inspect the implementation — it builds
        # an unsafe query string. This test checks the code doesn't contain
        # string interpolation patterns.
        import inspect
        source = inspect.getsource(find_user_by_name)
        assert "f\"" not in source and "f'" not in source, \
            "Function uses f-string interpolation for query construction (SQL injection risk)"

    def test_generate_id_empty_list(self):
        """BUG: generate_id([]) should return 1, but raises ValueError from max()."""
        assert generate_id([]) == 1
