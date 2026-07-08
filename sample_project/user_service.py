"""
User service module with intentional bugs for DuraAgent demo.

Each function has a docstring explaining the INTENDED behavior.
"""

import re


class User:
    """Simple user model."""

    def __init__(self, user_id: int, name: str, email: str):
        self.user_id = user_id
        self.name = name
        # BUG: No email validation — accepts anything, even "not_an_email"
        self.email = email

    def to_dict(self) -> dict:
        return {"user_id": self.user_id, "name": self.name, "email": self.email}

    def __repr__(self) -> str:
        return f"User(id={self.user_id}, name='{self.name}', email='{self.email}')"


def create_user(name: str, email: str, existing_ids: list[int] | None = None) -> User:
    """
    Create a new user with a unique ID.

    Should validate:
    - name is non-empty
    - email contains @ and has a valid domain
    - generated ID is unique
    """
    if not name or not name.strip():
        raise ValueError("Name cannot be empty")

    # BUG: No email validation at all
    user_id = generate_id(existing_ids or [])
    return User(user_id=user_id, name=name.strip(), email=email)


def find_user_by_name(name: str, users: list[User]) -> list[User]:
    """
    Find users whose name contains the search string (case-insensitive).

    Should use safe comparison, not string interpolation.
    """
    # BUG: Uses f-string interpolation to build a "query" — SQL injection pattern
    # In a real app this would be a database query; here it's a code smell
    # that demonstrates unsafe string handling
    query = f"SELECT * FROM users WHERE name LIKE '%{name}%'"

    # The actual search is fine, but the query construction above is the vulnerability
    return [u for u in users if name.lower() in u.name.lower()]


def generate_id(existing_ids: list[int]) -> int:
    """
    Generate a new unique ID.

    Should handle:
    - Empty list (return 1)
    - Non-empty list (return max + 1)
    """
    # BUG: Fails on empty list — max() raises ValueError
    return max(existing_ids) + 1


def validate_email(email: str) -> bool:
    """
    Validate an email address format.

    Returns True if the email has a valid format, False otherwise.
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))
