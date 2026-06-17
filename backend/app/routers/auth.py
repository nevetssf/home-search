"""Auth + user management. 2–3 named household users (PLAN.md §1)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token({"sub": user.email})
    return schemas.Token(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(current: User = Depends(get_current_user)):
    return current


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=schemas.UserOut, status_code=201)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Create an additional household user. Requires an existing authenticated
    user (bootstrap the first user via the seed script / CLI)."""
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/me/password", status_code=204)
def change_password(
    payload: schemas.PasswordChange,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Change the current user's own password (verifies the current one first)."""
    if not verify_password(payload.current_password, current.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current.hashed_password = get_password_hash(payload.new_password)
    db.commit()


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Delete a household user. Self-deletion is blocked to avoid lockout."""
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
