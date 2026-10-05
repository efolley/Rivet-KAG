from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.api.deps import DbSessionDep, RequiredUserIdDep, SettingsDep
from src.auth import create_access_token, hash_password, verify_password
from src.db import User
from src.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: DbSessionDep, settings: SettingsDep) -> TokenResponse:
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from e
    return TokenResponse(access_token=create_access_token(user.id, settings))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: DbSessionDep, settings: SettingsDep) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == req.email))).scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return TokenResponse(access_token=create_access_token(user.id, settings))


@router.get("/me", response_model=UserResponse)
async def me(user_id: RequiredUserIdDep, db: DbSessionDep) -> UserResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return UserResponse(id=user.id, email=user.email)
