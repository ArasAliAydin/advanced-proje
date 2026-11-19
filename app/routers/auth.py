from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.core.deps import CurrentUser, SessionDep
from app.core.security import create_access_token, hash_password, verify_password
from app.models import PenaltyLog, User
from app.schemas import PenaltyRead, Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, session: SessionDep):
    """Yeni öğrenci hesabı oluşturur. Admin rolü yalnızca mevcut bir admin tarafından verilebilir."""
    email = data.email.lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu e-posta adresi zaten kayıtlı")
    user = User(email=email, full_name=data.full_name.strip(), hashed_password=hash_password(data.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep):
    """OAuth2 password flow: `username` alanına e-posta yazılır. JWT access token döner."""
    user = session.exec(select(User).where(User.email == form.username.lower())).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "E-posta veya şifre hatalı", headers={"WWW-Authenticate": "Bearer"}
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hesabınız devre dışı bırakılmış")
    return Token(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user


@router.get("/me/penalties", response_model=list[PenaltyRead])
def my_penalties(user: CurrentUser, session: SessionDep):
    stmt = select(PenaltyLog).where(PenaltyLog.user_id == user.id).order_by(PenaltyLog.created_at.desc())
    return session.exec(stmt).all()
