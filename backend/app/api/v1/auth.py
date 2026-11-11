from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User, UserRole
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserLogin, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account"
)
def register_user(
    user_in: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Registers a new user account.
    If this is the first user in the database, automatically grants ADMIN role.
    Otherwise, default role is assigned.
    """
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists."
        )

    # First registered user becomes the platform Administrator
    user_count = db.query(User).count()
    assigned_role = UserRole.ADMIN.value if user_count == 0 else user_in.role.value

    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=assigned_role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="Authenticate and receive JWT access token (Form/Swagger)"
)
def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2 compatible token login, getting an access token for future requests.
    Supports standard Swagger UI authorize button.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account"
        )

    access_token = create_access_token(subject=user.id, role=user.role)
    return Token(
        access_token=access_token,
        token_type="bearer",
        role=user.role,
        user_id=user.id
    )


@router.post(
    "/login/json",
    response_model=Token,
    summary="Authenticate via JSON payload"
)
def login_json(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """JSON-based alternative login for modern frontend single-page applications."""
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account"
        )

    access_token = create_access_token(subject=user.id, role=user.role)
    return Token(
        access_token=access_token,
        token_type="bearer",
        role=user.role,
        user_id=user.id
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Retrieve current authenticated user session"
)
def read_current_user(
    current_user: User = Depends(get_current_user)
):
    """Returns the profile information of the currently authenticated user."""
    return current_user


@router.get(
    "/admin-only",
    summary="Protected endpoint for administrator role verification"
)
def admin_verification_route(
    current_admin: User = Depends(require_admin)
):
    """Endpoint accessible only by users with ADMIN role."""
    return {
        "status": "authorized",
        "message": f"Welcome, Administrator {current_admin.full_name}",
        "admin_id": current_admin.id
    }
