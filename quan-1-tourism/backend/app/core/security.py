from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.domain import AdminUser, AuditLog, RefreshToken, RevokedToken
from app.services.runtime_store import store

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def issue_token(user_id: str, username: str, role: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "username": username, "role": role, "jti": str(uuid4()), "exp": expires}, settings.JWT_SECRET, algorithm="HS256")


def _refresh_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def issue_refresh_token(user: dict, session: AsyncSession | None) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token_hash = _refresh_hash(token)
    if session is None:
        store.refresh_tokens[token_hash] = {"user": dict(user), "expires_at": expires_at, "revoked_at": None}
    else:
        session.add(RefreshToken(token_hash=token_hash, user_id=user["id"], expires_at=expires_at))
        await session.commit()
    return token


async def rotate_refresh_token(token: str | None, session: AsyncSession | None) -> tuple[dict, str] | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    token_hash = _refresh_hash(token)
    if session is None:
        old = store.refresh_tokens.get(token_hash)
        if not old or old["revoked_at"] is not None or old["expires_at"] <= now:
            return None
        old["revoked_at"] = now
        user = old["user"]
        return user, await issue_refresh_token(user, None)

    old = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())
    if old is None or old.revoked_at is not None or old.expires_at <= now:
        await session.rollback()
        return None
    user_row = await session.get(AdminUser, old.user_id)
    if user_row is None or not user_row.is_active:
        old.revoked_at = now
        await session.commit()
        return None
    user = {"id": user_row.id, "username": user_row.username, "role": user_row.role}
    old.revoked_at = now
    next_token = secrets.token_urlsafe(48)
    session.add(RefreshToken(token_hash=_refresh_hash(next_token), user_id=user_row.id, expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)))
    await session.commit()
    return user, next_token


async def revoke_refresh_token(token: str | None, session: AsyncSession | None) -> None:
    if not token:
        return
    now = datetime.now(timezone.utc)
    token_hash = _refresh_hash(token)
    if session is None:
        row = store.refresh_tokens.get(token_hash)
        if row:
            row["revoked_at"] = now
        return
    row = await session.get(RefreshToken, token_hash)
    if row and row.revoked_at is None:
        row.revoked_at = now
        await session.commit()


async def bootstrap_admin() -> None:
    from app.core.database import db

    if db.session_factory is None:
        return
    async with db.session_factory() as session:
        user = await session.scalar(select(AdminUser).where(AdminUser.username == settings.ADMIN_USERNAME))
        if user is None:
            session.add(AdminUser(id=str(uuid4()), username=settings.ADMIN_USERNAME, password_hash=hash_password(settings.ADMIN_PASSWORD), role="ADMIN"))
            await session.commit()


async def authenticate(username: str, password: str, session: AsyncSession | None) -> dict | None:
    if session is None:
        if username == settings.ADMIN_USERNAME and secrets.compare_digest(password, settings.ADMIN_PASSWORD):
            return {"id": "demo-admin", "username": username, "role": "ADMIN"}
        user = next((item for item in store.users.values() if item["username"] == username and item["is_active"]), None)
        if user and verify_password(password, user["password_hash"]):
            return {"id": user["id"], "username": username, "role": user["role"]}
        return None
    user = await session.scalar(select(AdminUser).where(AdminUser.username == username, AdminUser.is_active.is_(True)))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return {"id": user.id, "username": user.username, "role": user.role}


async def get_current_user(token: str = Depends(oauth2_scheme), session: AsyncSession | None = Depends(get_session)) -> dict:
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        token_id = payload.get("jti")
        if not user_id or not token_id:
            raise credentials_error
    except jwt.PyJWTError as exc:
        raise credentials_error from exc
    token_expires_at = datetime.fromtimestamp(payload["exp"], timezone.utc)
    if session is None:
        now = datetime.now(timezone.utc)
        store.revoked_tokens = {key: expiry for key, expiry in store.revoked_tokens.items() if expiry > now}
        if token_id in store.revoked_tokens:
            raise credentials_error
        if user_id == "demo-admin":
            return {"id": user_id, "username": payload.get("username", "admin"), "role": "ADMIN", "token_id": token_id, "token_expires_at": token_expires_at}
        user = store.users.get(user_id)
        if not user or not user["is_active"]:
            raise credentials_error
        return {"id": user_id, "username": user["username"], "role": user["role"], "token_id": token_id, "token_expires_at": token_expires_at}
    if await session.get(RevokedToken, token_id):
        raise credentials_error
    user = await session.get(AdminUser, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return {"id": user.id, "username": user.username, "role": user.role, "token_id": token_id, "token_expires_at": token_expires_at}


async def revoke_token(session: AsyncSession | None, user: dict) -> None:
    token_id = user["token_id"]
    expires_at = user["token_expires_at"]
    if session is None:
        now = datetime.now(timezone.utc)
        store.revoked_tokens = {key: expiry for key, expiry in store.revoked_tokens.items() if expiry > now}
        store.revoked_tokens[token_id] = expires_at
        return
    now = datetime.now(timezone.utc)
    await session.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
    session.add(RevokedToken(jti=token_id, expires_at=expires_at))
    await session.commit()


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return user


async def require_reviewer(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in {"ADMIN", "REVIEWER"}:
        raise HTTPException(status_code=403, detail="Reviewer permission required")
    return user


async def write_audit(session: AsyncSession | None, actor: dict, action: str, target_type: str, target_id: str | None = None, details: dict | None = None) -> None:
    row = {"id": str(uuid4()), "actor_id": actor["id"], "action": action, "target_type": target_type, "target_id": target_id, "details": details or {}, "created_at": datetime.now(timezone.utc).isoformat()}
    if session is None:
        store.audit.insert(0, row)
        del store.audit[500:]
        return
    session.add(AuditLog(id=row["id"], actor_id=actor["id"], action=action, target_type=target_type, target_id=target_id, details=row["details"]))
    await session.commit()
