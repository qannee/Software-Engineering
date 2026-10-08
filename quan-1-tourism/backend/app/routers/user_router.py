from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.security import authenticate, get_current_user, hash_password, issue_refresh_token, issue_token, revoke_refresh_token, revoke_token, rotate_refresh_token
from app.models.domain import AdminUser, UserFavorite
from app.repositories.poi_repository import POIRepository
from app.schemas.admin import AdminLogin, UserRegister
from app.services.runtime_store import store

router = APIRouter(tags=["User account"])
USER_REFRESH_COOKIE = "q1_user_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=USER_REFRESH_COOKIE,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.APP_ENV.lower() == "production",
        samesite=settings.REFRESH_COOKIE_SAMESITE.lower(),
        path=f"{settings.API_V1_STR}/auth",
    )


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed for authentication")


def _session_payload(user: dict) -> dict:
    return {"access_token": issue_token(user["id"], user["username"], user["role"]), "token_type": "bearer", "user": {"username": user["username"], "role": user["role"]}}


async def require_user(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "USER":
        raise HTTPException(status_code=403, detail="User account required")
    return user


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, response: Response, request: Request, session: AsyncSession | None = Depends(get_session)):
    _check_origin(request)
    username = body.username.strip()
    if username.lower() == settings.ADMIN_USERNAME.lower():
        raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
    user_id = str(uuid4())
    user = {"id": user_id, "username": username, "role": "USER"}
    if session is None:
        if any(item["username"].lower() == username.lower() for item in store.users.values()):
            raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
        store.users[user_id] = {**user, "password_hash": hash_password(body.password), "is_active": True}
    else:
        existing = await session.scalar(select(AdminUser).where(AdminUser.username.ilike(username)))
        if existing:
            raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
        session.add(AdminUser(id=user_id, username=username, password_hash=hash_password(body.password), role="USER"))
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại") from exc
    _set_refresh_cookie(response, await issue_refresh_token(user, session))
    return _session_payload(user)


@router.post("/auth/login")
async def login(body: AdminLogin, response: Response, request: Request, session: AsyncSession | None = Depends(get_session)):
    _check_origin(request)
    user = await authenticate(body.username.strip(), body.password, session)
    if not user or user["role"] != "USER":
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không đúng")
    _set_refresh_cookie(response, await issue_refresh_token(user, session))
    return _session_payload(user)


@router.post("/auth/refresh")
async def refresh(request: Request, response: Response, refresh_cookie: str | None = Cookie(default=None, alias=USER_REFRESH_COOKIE), session: AsyncSession | None = Depends(get_session)):
    _check_origin(request)
    rotated = await rotate_refresh_token(refresh_cookie, session)
    if not rotated or rotated[0]["role"] != "USER":
        raise HTTPException(status_code=401, detail="Refresh session is invalid or expired")
    user, next_refresh = rotated
    _set_refresh_cookie(response, next_refresh)
    return _session_payload(user)


@router.get("/auth/me")
async def me(user: dict = Depends(require_user)):
    return {"username": user["username"], "role": user["role"]}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, refresh_cookie: str | None = Cookie(default=None, alias=USER_REFRESH_COOKIE), session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_user)):
    _check_origin(request)
    await revoke_token(session, user)
    await revoke_refresh_token(refresh_cookie, session)
    response.delete_cookie(USER_REFRESH_COOKIE, path=f"{settings.API_V1_STR}/auth", secure=settings.APP_ENV.lower() == "production", httponly=True, samesite=settings.REFRESH_COOKIE_SAMESITE.lower())
    return {"logged_out": True}


@router.get("/user/favorites")
async def get_favorites(session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_user)):
    if session is None:
        return {"data": sorted(store.user_favorites.get(user["id"], set()))}
    rows = await session.scalars(select(UserFavorite.poi_id).where(UserFavorite.user_id == user["id"]).order_by(UserFavorite.created_at.desc()))
    return {"data": list(rows.all())}


@router.put("/user/favorites/{poi_id}", status_code=status.HTTP_201_CREATED)
async def add_favorite(poi_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_user)):
    poi = await POIRepository(session).get_by_id(poi_id)
    if not poi or poi.get("status") != "PUBLISHED":
        raise HTTPException(status_code=404, detail="Không tìm thấy địa điểm")
    if session is None:
        store.user_favorites.setdefault(user["id"], set()).add(poi_id)
    else:
        if not await session.get(UserFavorite, (user["id"], poi_id)):
            session.add(UserFavorite(user_id=user["id"], poi_id=poi_id))
            await session.commit()
    return {"poi_id": poi_id, "favorite": True}


@router.delete("/user/favorites/{poi_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(poi_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_user)):
    if session is None:
        store.user_favorites.setdefault(user["id"], set()).discard(poi_id)
    else:
        await session.execute(delete(UserFavorite).where(UserFavorite.user_id == user["id"], UserFavorite.poi_id == poi_id))
        await session.commit()
