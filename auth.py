import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Security, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwt
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env.local")
load_dotenv(BASE_DIR.parent / ".env", override=False)

from database import get_db
from models import AdminSession, AdminUser, UserProfile
from services import create_or_update_user_profile

security = HTTPBearer(auto_error=False)

SUPABASE_AUD = os.getenv("SUPABASE_AUD", "authenticated")
SUPABASE_ALGORITHM = os.getenv("SUPABASE_JWT_ALGORITHM", "HS256").upper()
SUPABASE_JWT_PUBLIC_KEY = os.getenv("SUPABASE_JWT_PUBLIC_KEY")

# Internal tokens issued by our backend to represent sessions to frontend/backend APIs.
# HS256 works out of the box for local/dev. Set INTERNAL_JWT_ALGORITHM plus
# INTERNAL_JWT_PRIVATE_KEY/INTERNAL_JWT_PUBLIC_KEY to use asymmetric signing.
INTERNAL_JWT_ALGORITHM = os.getenv("INTERNAL_JWT_ALGORITHM", "HS256").upper()
INTERNAL_JWT_SECRET = (
    os.getenv("INTERNAL_JWT_SECRET")
    or os.getenv("JWT_SECRET")
    or os.getenv("SECRET_KEY")
    or "foodvault-local-dev-secret-change-me"
)
INTERNAL_JWT_PRIVATE_KEY = os.getenv("INTERNAL_JWT_PRIVATE_KEY")
INTERNAL_JWT_PUBLIC_KEY = os.getenv("INTERNAL_JWT_PUBLIC_KEY")
INTERNAL_JWT_EXPIRES_SECONDS = int(os.getenv("INTERNAL_JWT_EXPIRES_SECONDS", "3600"))


def get_supabase_jwt_key() -> str:
    if SUPABASE_ALGORITHM == "RS256":
        if not SUPABASE_JWT_PUBLIC_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SUPABASE_JWT_PUBLIC_KEY is required for RS256 token verification",
            )
        return SUPABASE_JWT_PUBLIC_KEY

    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase JWT secret is not configured",
        )
    return secret


def decode_supabase_token(token: str) -> dict:
    key = get_supabase_jwt_key()
    try:
        header = jwt.get_unverified_header(token)
        token_alg = header.get("alg")
        if token_alg != SUPABASE_ALGORITHM:
            raise JWTError(
                f"token alg={token_alg} does not match configured SUPABASE_JWT_ALGORITHM={SUPABASE_ALGORITHM}"
            )
        return jwt.decode(token, key, algorithms=[SUPABASE_ALGORITHM], audience=SUPABASE_AUD)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid authentication token: {exc}")


def get_supabase_claims(token: str) -> dict:
    print("[AUTH] Using Supabase verification only", flush=True)

    return fetch_supabase_user_claims(
        token,
        HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase verification failed",
        ),
    )


def fetch_supabase_user_claims(token: str, fallback_error: HTTPException) -> dict:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    )

    if not supabase_url or not supabase_key:
        raise fallback_error

    try:
        response = httpx.get(
            f"{supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unable to verify Supabase session: {exc}",
        )

    if response.status_code >= 400:
        raise fallback_error

    user = response.json()
    user_metadata = user.get("user_metadata") or {}
    app_metadata = user.get("app_metadata") or {}
    return {
        "sub": user.get("id"),
        "email": user.get("email"),
        "name": user_metadata.get("full_name") or user_metadata.get("name") or user.get("email"),
        "role": app_metadata.get("role") or user_metadata.get("role") or "customer",
        "user_metadata": user_metadata,
        "app_metadata": app_metadata,
    }


def get_internal_signing_key() -> str:
    if INTERNAL_JWT_ALGORITHM.startswith(("ES", "PS", "RS")):
        if not INTERNAL_JWT_PRIVATE_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INTERNAL_JWT_PRIVATE_KEY is required to sign internal ES/PS/RS tokens",
            )
        return INTERNAL_JWT_PRIVATE_KEY

    return INTERNAL_JWT_SECRET


def get_internal_verification_key() -> str:
    if INTERNAL_JWT_ALGORITHM.startswith(("ES", "PS", "RS")):
        key = INTERNAL_JWT_PUBLIC_KEY or INTERNAL_JWT_PRIVATE_KEY
        if not key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INTERNAL_JWT_PUBLIC_KEY or INTERNAL_JWT_PRIVATE_KEY is required to verify internal ES/PS/RS tokens",
            )
        return key

    return INTERNAL_JWT_SECRET


def create_internal_token(claims: dict) -> str:
    if "jti" not in claims:
        claims["jti"] = str(uuid.uuid4())

    payload = {**claims}

    if INTERNAL_JWT_ALGORITHM.startswith(("ES", "PS", "RS")) and not INTERNAL_JWT_PRIVATE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL_JWT_PRIVATE_KEY is required to sign internal ES/PS/RS tokens",
        )

    # set expiry
    import time

    payload["iat"] = int(time.time())
    payload["exp"] = int(time.time()) + INTERNAL_JWT_EXPIRES_SECONDS

    return jwt.encode(payload, get_internal_signing_key(), algorithm=INTERNAL_JWT_ALGORITHM)


def hash_auth_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_internal_token(token: str) -> dict:
    key = get_internal_verification_key()
    try:
        header = jwt.get_unverified_header(token)
        token_alg = header.get("alg")
        if token_alg != INTERNAL_JWT_ALGORITHM:
            raise JWTError(f"internal token alg={token_alg} does not match expected={INTERNAL_JWT_ALGORITHM}")
        return jwt.decode(token, key, algorithms=[INTERNAL_JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid internal token: {exc}")


def get_current_user(
    request: Request, authorization: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)
) -> UserProfile:
    """Get current user from backend session or Supabase token.
    
    Flow:
    1. Try fv_token cookie (set by backend after auth exchange)
    2. Try Authorization header with internal backend token
    3. Try Authorization header with Supabase token (exchange flow)
    """
    data = None
    token_source = None
    
    # Try fv_token cookie first (preferred - set by backend)
    fv_cookie = request.cookies.get("fv_token")
    if fv_cookie:
        try:
            data = decode_internal_token(fv_cookie)
            token_source = "fv_token cookie"
        except HTTPException as e:
            print(f"[auth] fv_token cookie validation failed: {e.detail}", flush=True)
            data = None

    # Try Authorization header with internal backend token
    if not data and authorization and authorization.credentials:
        try:
            data = decode_internal_token(authorization.credentials)
            token_source = "Authorization header (internal token)"
        except HTTPException as e:
            print(f"[auth] Internal token validation failed: {e.detail}, trying Supabase...", flush=True)
            # Fall through to Supabase
            try:
                data = get_supabase_claims(authorization.credentials)
                token_source = "Authorization header (Supabase token)"
            except HTTPException as e2:
                print(f"[auth] Supabase token validation also failed: {e2.detail}", flush=True)
                data = None

    if not data:
        print("[auth] No valid authentication token found", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    supabase_id = data.get("sub")
    if not supabase_id:
        print("[auth] Invalid token payload - missing sub claim", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    print(f"[auth] User authenticated via {token_source}: {data.get('email')}", flush=True)

    # Get or create user profile
    user = db.query(UserProfile).filter(UserProfile.supabase_user_id == supabase_id).one_or_none()
    if not user:
        print(f"[auth] User profile not found for {supabase_id}, creating...", flush=True)
        user = create_or_update_user_profile(db, data)
    
    return user


def get_admin_user(
    request: Request, authorization: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)
) -> UserProfile:
    """Authenticate admin user. Admin sessions are completely separate from regular user sessions.
    
    Admin session must:
    1. Have valid fv_admin_token cookie or Authorization header with admin token
    2. Have active session record in AdminSession table
    3. Not be expired
    4. Have admin role or admin record mapping
    """
    data = None
    raw_token = None
    token_source = None
    
    # Try fv_admin_token cookie first
    fv_admin_cookie = request.cookies.get("fv_admin_token")
    if fv_admin_cookie:
        try:
            data = decode_internal_token(fv_admin_cookie)
            raw_token = fv_admin_cookie
            token_source = "fv_admin_token cookie"
        except HTTPException as e:
            print(f"[auth] Admin cookie validation failed: {e.detail}", flush=True)
            data = None

    # Try Authorization header
    if not data and authorization and authorization.credentials:
        try:
            data = decode_internal_token(authorization.credentials)
            raw_token = authorization.credentials
            token_source = "Authorization header"
        except HTTPException as e:
            print(f"[auth] Admin auth header validation failed: {e.detail}", flush=True)
            data = None

    if not data:
        print("[auth] No valid admin authentication token found", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not authenticated")

    if not raw_token:
        print("[auth] Admin token is missing", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token is missing")

    # Check admin session validity
    token_hash = hash_auth_token(raw_token)
    session = (
        db.query(AdminSession)
        .filter(AdminSession.token_hash == token_hash, AdminSession.is_active.is_(True))
        .one_or_none()
    )
    
    if not session:
        print(f"[auth] No active admin session found for token hash", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session is invalid or revoked")
    
    # Check expiration
    if session.expires_at and session.expires_at < datetime.utcnow():
        print(f"[auth] Admin session expired at {session.expires_at}", flush=True)
        session.is_active = False
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")

    # Update last seen
    session.last_seen_at = datetime.utcnow()
    db.commit()

    # Get user and verify admin role
    supabase_id = data.get("sub")
    if not supabase_id:
        print("[auth] Invalid admin token - missing sub claim", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token payload")

    user = db.query(UserProfile).filter(UserProfile.supabase_user_id == supabase_id).one_or_none()
    if not user:
        print(f"[auth] Admin user profile not found for {supabase_id}, creating...", flush=True)
        user = create_or_update_user_profile(db, data)

    # Verify admin access
    role = data.get("role") or data.get("user_metadata", {}).get("role")
    if role != "admin":
        admin_record = db.query(AdminUser).filter(AdminUser.user_profile_id == user.id).one_or_none()
        if not admin_record:
            print(f"[auth] User {supabase_id} does not have admin access", flush=True)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    print(f"[auth] Admin authenticated via {token_source}: {data.get('email')}", flush=True)
    return user


def require_admin_user(current_user: UserProfile = Depends(get_admin_user), db: Session = Depends(get_db)) -> UserProfile:
    # Backwards-compatible: if current_user is already an admin, allow
    if current_user.role == "admin":
        return current_user

    # Check explicit admin record mapping
    admin_record = db.query(AdminUser).filter(AdminUser.user_profile_id == current_user.id).one_or_none()
    if admin_record:
        return current_user

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
