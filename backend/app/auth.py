"""Local demo sign-in: API keys mapped to a teacher and two students. Production would use the district's
identity provider (OIDC/SAML through Cognito or similar) with the same role checks."""
from dataclasses import dataclass

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str  # TEACHER | STUDENT


USERS = {
    "teacher-key": User("T-RIVERA", "Ms. Rivera", "TEACHER"),
    "maya-key": User("STU-MAYA", "Maya", "STUDENT"),
    "leo-key": User("STU-LEO", "Leo", "STUDENT"),
}


def current_user(x_api_key: str | None = Header(default=None)) -> User:
    user = USERS.get(x_api_key or "")
    if user is None:
        raise HTTPException(401, "Send a valid X-API-Key header")
    return user


def require_teacher(user: User) -> None:
    if user.role != "TEACHER":
        raise HTTPException(403, "Teachers only")
