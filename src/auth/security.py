"""Password hashing and JWT issuance/verification. Stateless JWTs: no server-side session
store, so there's no login/logout session state to keep in Redis — Redis's role in this
project is response caching (src/clients/redis.py), not session storage. See the README's
Phase 3 notes for why.
"""

from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from src.config import Settings

_ALGORITHM = "HS256"
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(user_id: int, settings: Settings) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_ttl_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_user_id(token: str, settings: Settings) -> int | None:
    """Returns the user id encoded in a valid, unexpired token, or None otherwise."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    return int(subject) if subject is not None else None
