from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, get_current_user,
)
from app.models.user import User
from app.schemas import RegisterRequest, LoginRequest, AnonymousLoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user": UserOut.model_validate(user),
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        name=body.name,
    )
    db.add(user)
    await db.commit()
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")

    return _token_response(user)


@router.post("/anonymous", response_model=TokenResponse, status_code=201)
async def login_anonymous(body: AnonymousLoginRequest, db: AsyncSession = Depends(get_db)):
    # Return existing anonymous user for the same device_id
    result = await db.execute(select(User).where(User.device_id == body.device_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(device_id=body.device_id, is_anonymous=True)
        db.add(user)
        await db.commit()

    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    # Accept refresh token from body or Authorization header
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    token = body.get("refresh_token") or (request.headers.get("Authorization", "").replace("Bearer ", "") or None)

    if not token:
        raise HTTPException(401, "Refresh token required")

    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found")

    return _token_response(user)


@router.post("/logout", status_code=204)
async def logout(current_user: User = Depends(get_current_user)):
    # Stateless JWT — client discards tokens
    # TODO: add token blacklist via Redis for extra security
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
