import os
import re
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

#from backend import auth, services, database, models
import auth
import services
import database
import models
import httpx
#from backend.database import get_db, init_db
from database import get_db, init_db
from models import AdminSession, AdminUser, CartItem, Order, Payment, Product, ReserveVault, ReserveItem, DeliverySchedule, Inventory, UserProfile
from phase2_routes import router as phase2_router
from phase2_services import create_referral_commission_for_order
from routes.payment_routes import router as payment_router
from webhooks.stripe_webhooks import router as stripe_webhook_router

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env.local")
load_dotenv(BASE_DIR.parent / ".env", override=False)

UPLOAD_DIR = BASE_DIR.parent / "uploads" / "products"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4028",
    "http://127.0.0.1:4028",
]
frontend_origins = os.getenv("FRONTEND_URL", "").strip()
raw_origins = [origin.strip() for origin in frontend_origins.split(",") if origin.strip()]
allowed_origins = sorted(set(raw_origins + DEFAULT_LOCAL_ORIGINS))
if not allowed_origins:
    allowed_origins = DEFAULT_LOCAL_ORIGINS

localhost_origin_regex = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


def is_allowed_origin(origin: Optional[str]) -> bool:
    if not origin:
        return False
    if origin in allowed_origins:
        return True
    return localhost_origin_regex.match(origin) is not None


app_env = os.getenv("APP_ENV", os.getenv("NODE_ENV", "development")).lower()
print(f"[api] CORS allowed origins: {allowed_origins} (env={app_env}) - main.py:63", flush=True)

def use_secure_cookies() -> bool:
    insecure_override = os.getenv("DEV_INSECURE_COOKIES", "").lower()
    if insecure_override in {"1", "true", "yes", "on"}:
        return False

    app_env = os.getenv("APP_ENV", os.getenv("NODE_ENV", "development")).lower()
    if app_env in {"dev", "development", "local", "test"}:
        return False

    return True

app = FastAPI(title="FoodVault Monolithic Backend", version="1.0")

# CORS middleware must be registered immediately after app creation
# so OPTIONS requests and credentialed cross-origin requests are handled first.
# Enhanced configuration for file uploads with explicit headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-CSRF-Token",
        "Cache-Control",
        "Pragma",
        "*",
    ],
    expose_headers=[
        "Content-Type",
        "Content-Length",
        "Content-Disposition",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-XSS-Protection",
        "*",
    ],
    max_age=86400,  # 24 hours cache for CORS preflight
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.include_router(phase2_router)
app.include_router(payment_router)
app.include_router(stripe_webhook_router)


# Custom middleware to ensure CORS headers are always set for file uploads
@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    """
    Explicitly handle CORS for all requests, especially file uploads.
    Ensures Access-Control-Allow-Origin is set on all responses.
    """
    origin = request.headers.get("origin")
    
    # Handle OPTIONS preflight requests
    if request.method == "OPTIONS":
        allowed_origin = origin if is_allowed_origin(origin) else allowed_origins[0]
        response_headers = {
            "Access-Control-Allow-Origin": allowed_origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Type, Authorization, X-Requested-With, X-CSRF-Token, Cache-Control, Pragma",
            "Access-Control-Expose-Headers": "Content-Type, Content-Length, Content-Disposition, X-Content-Type-Options, X-Frame-Options, X-XSS-Protection",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",
        }
        return JSONResponse(status_code=200, content={}, headers=response_headers)
    
    # Process the actual request
    response = await call_next(request)
    
    # Ensure CORS headers are set on the response for all requests
    if is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    elif allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = allowed_origins[0]
        response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        print(f"[api] ERROR {request.method} {request.url.path} after {duration_ms:.1f}ms: {exc} - main.py:159", flush=True)
        raise

    if request.url.path.startswith("/api/"):
        duration_ms = (time.perf_counter() - started) * 1000
        cors_origin = response.headers.get("Access-Control-Allow-Origin", "none")
        print(f"[api] {request.method} {request.url.path} > {response.status_code} (CORS: {cors_origin}) ({duration_ms:.1f}ms) - main.py:165", flush=True)

    return response



class AuthExchangePayload(BaseModel):
    access_token: str


class AdminLoginPayload(BaseModel):
    username: str
    password: str


def persist_user_profile_from_claims(claims: dict) -> None:
    db = database.SessionLocal()
    try:
        services.create_or_update_user_profile(db, claims)
    finally:
        db.close()


def set_session_cookie(res: JSONResponse, key: str, value: str, max_age: int) -> None:
    """Set session cookie with secure and stable rules for auth.

    - `path='/'` ensures the cookie is available across the site.
    - `sameSite='lax'` keeps auth cookies available for same-site navigation.
    - `secure` is enabled only in production.
    """
    secure = use_secure_cookies()
    res.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


@app.post("/api/auth/exchange")
def api_auth_exchange(payload: AuthExchangePayload):
    """Exchange a Supabase access token for an internal backend session cookie.

    Frontend should POST `{ access_token }` after completing Supabase sign-in.
    """
    claims = auth.get_supabase_claims(payload.access_token)
    persist_user_profile_from_claims(claims)
    internal = auth.create_internal_token(claims)
    res = JSONResponse(status_code=200, content={"ok": True, "auth_token": internal})
    set_session_cookie(res, "fv_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


class AuthCredentials(BaseModel):
    email: str
    password: str
    metadata: Optional[Dict[str, str]] = None


@app.post("/api/auth/signup")
async def api_auth_signup(payload: AuthCredentials):
    """Create a Supabase user (server-side) and set internal session cookie.

    Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in env.
    """
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not SUPABASE_URL or not SERVICE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service key / URL not configured on server")

    signup_payload = {"email": payload.email, "password": payload.password}
    if payload.metadata:
        signup_payload["data"] = payload.metadata

    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{SUPABASE_URL.rstrip('/')}/auth/v1/signup",
                json=signup_payload,
                headers=headers,
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Error contacting Supabase: {e}")

    if resp.status_code >= 400:
        # forward Supabase error body where possible
        try:
            data = resp.json()
        except Exception:
            data = {"error": "signup_failed", "status_code": resp.status_code}
        raise HTTPException(status_code=400, detail=data)

    data = resp.json()
    # successful signup may return user and session (with access_token)
    user = data.get("user") or data.get("data")
    access_token = data.get("access_token") or (data.get("session") or {}).get("access_token")
    if not user:
        raise HTTPException(status_code=500, detail="Supabase did not return user on signup")

    claims = {"sub": user.get("id"), "email": user.get("email")}
    if payload.metadata:
        claims.update(payload.metadata)
    persist_user_profile_from_claims(claims)
    internal = auth.create_internal_token(claims)
    res = JSONResponse(status_code=200, content={"user": user, "auth_token": internal})
    set_session_cookie(res, "fv_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    """Authenticate via Supabase (password grant) and set internal session cookie.

    This endpoint is tolerant of incoming request bodies that may be JSON, form-encoded,
    or have a mismatched Content-Type header (some clients have been observed to send
    an empty JSON Content-Type). We try multiple parsers to avoid returning a confusing
    "bad_json" error to the client.
    """
    print("[auth] Entered /api/auth/login handler", flush=True)
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not SUPABASE_URL or not SERVICE_KEY:
        raise HTTPException(status_code=500, detail="Supabase service key / URL not configured on server")

    # Try to read email/password from raw body once (avoid consuming stream twice)
    email = None
    password = None
    try:
        content_type = request.headers.get('content-type', '')
        print(f"[auth] /api/auth/login Content-Type: {content_type}", flush=True)
        raw = await request.body()
        raw_preview = raw[:200] if raw else b''
        print(f"[auth] /api/auth/login raw body preview (first 200 bytes): {raw_preview}", flush=True)

        if raw:
            # Parse based on content type
            if 'application/json' in content_type:
                import json as _json

                parsed = _json.loads(raw.decode('utf-8'))
                email = parsed.get('email')
                password = parsed.get('password')
            elif 'application/x-www-form-urlencoded' in content_type:
                from urllib.parse import parse_qs

                qs = parse_qs(raw.decode('utf-8'))
                email = qs.get('email', [None])[0]
                password = qs.get('password', [None])[0]
            else:
                # Try best-effort JSON then urlencoded
                try:
                    import json as _json

                    parsed = _json.loads(raw.decode('utf-8'))
                    email = parsed.get('email')
                    password = parsed.get('password')
                except Exception:
                    try:
                        from urllib.parse import parse_qs

                        qs = parse_qs(raw.decode('utf-8'))
                        email = qs.get('email', [None])[0]
                        password = qs.get('password', [None])[0]
                    except Exception:
                        pass
            # Last-resort: try to extract email/password with regex from raw text
            if (not email or not password) and raw:
                try:
                    import re

                    text = raw.decode('utf-8', errors='ignore')
                    if not email:
                        m = re.search(r'"email"\s*:\s*"([^"]+)"', text)
                        if m:
                            email = m.group(1)
                    if not password:
                        m2 = re.search(r'"password"\s*:\s*"([^"]+)"', text)
                        if m2:
                            password = m2.group(1)
                    print(f"[auth] /api/auth/login regex-extracted email={email} password={(bool(password) and '***') or None}", flush=True)
                except Exception as rex:
                    print(f"[auth] /api/auth/login regex extraction failed: {repr(rex)}", flush=True)
        else:
            # no body
            email = None
            password = None
    except Exception as exc:
        # If parsing failed entirely, print and surface a clearer error
        print(f"[auth] /api/auth/login parse exception: {repr(exc)}", flush=True)
        raise HTTPException(status_code=400, detail={"error": "bad_json", "msg": f"Could not parse request body: {repr(exc)}"})

    # Fallback: try query params
    if not email or not password:
        q_email = request.query_params.get('email')
        q_password = request.query_params.get('password')
        if q_email and q_password:
            email = q_email
            password = q_password

    if not email or not password:
        raise HTTPException(status_code=400, detail={"error": "missing_credentials", "msg": "email and password are required"})

    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"email": email, "password": password}
    token_url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    try:
        print(f"[auth] Posting to Supabase URL: {token_url}", flush=True)
        print(f"[auth] Supabase request headers: {{'apikey': '***', 'Authorization': '***', 'Content-Type': 'application/json'}}", flush=True)
        print(f"[auth] Supabase request data preview: email={data.get('email')} password={'***' if data.get('password') else None}", flush=True)
    except Exception:
        pass
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(token_url, json=data, headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}, timeout=10.0)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Error contacting Supabase: {e}")

    if resp.status_code >= 400:
        try:
            text = resp.text
        except Exception:
            text = '<unreadable body>'
        print(f"[auth] Supabase responded with status={resp.status_code} body={text}", flush=True)
        try:
            data = resp.json()
        except Exception:
            data = {"error": "login_failed", "status_code": resp.status_code, "body": text}
        raise HTTPException(status_code=400, detail=data)

    data = resp.json()
    access_token = data.get("access_token") or (data.get("session") or {}).get("access_token")
    user = data.get("user") or (data.get("session") or {}).get("user")
    if not access_token and not user:
        raise HTTPException(status_code=500, detail="Supabase did not return session on login")

    # prefer user id from returned user; if absent, try to decode supabase token
    sup_user_id = (user or {}).get("id") if user else None
    if not sup_user_id and access_token:
        try:
            sup_claims = auth.get_supabase_claims(access_token)
            sup_user_id = sup_claims.get("sub") or sup_claims.get("user_id")
            user = user or {"id": sup_user_id, "email": sup_claims.get("email")}
        except Exception:
            pass

    claims = {"sub": sup_user_id, "email": (user or {}).get("email")}
    persist_user_profile_from_claims(claims)
    internal = auth.create_internal_token(claims)
    res = JSONResponse(status_code=200, content={"user": user, "auth_token": internal})
    set_session_cookie(res, "fv_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


@app.post("/api/auth/logout")
def api_auth_logout():
    res = JSONResponse(status_code=200, content={"ok": True})
    res.delete_cookie("fv_token", path="/")
    return res


@app.get('/health')
def health_check(db: Session = Depends(get_db)):
    """Backend health check endpoint.

    Verifies the backend is running and can connect to the primary database.
    """
    try:
        # Execute a lightweight query to confirm the database connection.
        db.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database unavailable: {exc}")
    return {"status": "ok", "database": "ok"}


@app.get('/api/health')
def api_health_check():
    return {"status": "ok"}


@app.post("/api/admin/login")
def api_admin_login(payload: AdminLoginPayload, request: Request, db: Session = Depends(get_db)):
    """Authenticate admin user with username and password (local development only).
    
    Admin credentials are read from environment variables:
    - ADMIN_USERNAME (default: "admin")
    - ADMIN_PASSWORD (default: "admin@123")
    
    SECURITY WARNING: In production, use a proper identity provider or secure credential storage.
    Never hardcode credentials.
    """
    # Get expected credentials from environment
    expected_username = os.getenv("ADMIN_USERNAME", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", "admin@123")
    
    # Validate credentials
    if payload.username != expected_username or payload.password != expected_password:
        print(f"[auth] Admin login failed for username: {payload.username}", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")

    print(f"[auth] Admin login successful for username: {payload.username}", flush=True)
    
    claims = {
        "sub": "local-admin",
        "email": "admin@foodvault.local",
        "name": "Admin",
        "role": "admin",
    }
    persist_user_profile_from_claims(claims)

    user = db.query(UserProfile).filter(UserProfile.supabase_user_id == claims["sub"]).one_or_none()
    if not user:
        print("[auth] Failed to create admin profile", flush=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to create admin profile")

    admin_record = db.query(AdminUser).filter(AdminUser.user_profile_id == user.id).one_or_none()
    if not admin_record:
        admin_record = AdminUser(user_profile_id=user.id, is_superadmin=True)
        db.add(admin_record)
        db.commit()
        db.refresh(admin_record)

    internal = auth.create_internal_token(claims)
    token_hash = auth.hash_auth_token(internal)
    expires_at = datetime.utcnow() + timedelta(seconds=auth.INTERNAL_JWT_EXPIRES_SECONDS)
    session = AdminSession(
        admin_user_id=admin_record.id,
        token_hash=token_hash,
        jti=claims.get("jti") or "",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    res = JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "admin_token": internal,
            "session_id": session.id,
            "user": {"id": "local-admin", "email": claims["email"], "name": claims["name"], "role": "admin"},
        },
    )
    set_session_cookie(res, "fv_admin_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


@app.post("/api/admin/logout")
def api_admin_logout(request: Request, db: Session = Depends(get_db), current_user=Depends(auth.get_admin_user)):
    raw_token = request.cookies.get("fv_admin_token") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if raw_token:
        token_hash = auth.hash_auth_token(raw_token)
        session = db.query(AdminSession).filter(AdminSession.token_hash == token_hash, AdminSession.is_active.is_(True)).one_or_none()
        if session:
            session.is_active = False
            session.revoked_at = datetime.utcnow()
            db.commit()
    res = JSONResponse(status_code=200, content={"ok": True})
    res.delete_cookie("fv_admin_token", path="/")
    return res


@app.post("/api/admin/refresh")
def api_admin_refresh(request: Request, db: Session = Depends(get_db), current_user=Depends(auth.get_admin_user)):
    """Refresh admin token before it expires.
    
    This endpoint issues a new admin token with an extended expiration time.
    The current token remains valid until expiration.
    """
    print(f"[auth] Refreshing admin token for admin: {current_user.supabase_user_id}", flush=True)
    
    # Create new token with same claims as original
    claims = {
        "sub": current_user.supabase_user_id,
        "email": current_user.email or "admin@foodvault.local",
        "name": current_user.full_name or "Admin",
        "role": "admin",
    }
    
    internal = auth.create_internal_token(claims)
    token_hash = auth.hash_auth_token(internal)
    expires_at = datetime.utcnow() + timedelta(seconds=auth.INTERNAL_JWT_EXPIRES_SECONDS)
    
    # Create new session record
    session = AdminSession(
        admin_user_id=current_user.admin_record.id,
        token_hash=token_hash,
        jti=claims.get("jti") or "",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    
    res = JSONResponse(status_code=200, content={"ok": True, "admin_token": internal})
    set_session_cookie(res, "fv_admin_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


@app.post("/api/auth/refresh")
def api_auth_refresh(request: Request, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """Refresh user token before it expires.
    
    This endpoint issues a new user token with an extended expiration time.
    The current token remains valid until expiration.
    """
    print(f"[auth] Refreshing user token for user: {current_user.supabase_user_id}", flush=True)
    
    # Create new token with same claims as original
    claims = {
        "sub": current_user.supabase_user_id,
        "email": current_user.email,
        "name": current_user.full_name or "User",
        "role": current_user.role or "customer",
    }
    
    internal = auth.create_internal_token(claims)
    
    res = JSONResponse(status_code=200, content={"ok": True, "auth_token": internal})
    set_session_cookie(res, "fv_token", internal, auth.INTERNAL_JWT_EXPIRES_SECONDS)
    return res


@app.get("/api/admin/sessions")
def api_admin_sessions(db: Session = Depends(get_db), current_user=Depends(auth.get_admin_user)) -> List[Dict[str, object]]:
    if not current_user.admin_record:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    sessions = db.query(AdminSession).filter(AdminSession.admin_user_id == current_user.admin_record.id).order_by(AdminSession.created_at.desc()).all()
    return [services.model_to_dict(session) for session in sessions]


@app.delete("/api/admin/sessions/{session_id}")
def api_admin_revoke_session(session_id: int, db: Session = Depends(get_db), current_user=Depends(auth.get_admin_user)) -> JSONResponse:
    if not current_user.admin_record:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    session = db.query(AdminSession).filter(AdminSession.id == session_id, AdminSession.admin_user_id == current_user.admin_record.id).one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session.is_active = False
    session.revoked_at = datetime.utcnow()
    db.commit()
    return JSONResponse(status_code=200, content={"ok": True})


class ProfileUpdatePayload(BaseModel):
    name: Optional[str]
    phone: Optional[str]
    avatar_url: Optional[str]


class AddCartItemPayload(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    reserve_option: str = Field(default="purchase")
    partial_delivery: bool = False
    lock_duration_days: int = Field(default=100, ge=10, le=100)


class UpdateCartItemPayload(BaseModel):
    quantity: int = Field(default=1, ge=1)


class CheckoutPayload(BaseModel):
    payment_method: Optional[str] = "supabase-google"
    payment_intent_id: Optional[str] = None
    items: List[Dict[str, Any]] = []


class ReserveItemPayload(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    reserve_type: str = Field(default="deposit")
    partial_delivery: bool = False


class ReservePayload(BaseModel):
    items: List[ReserveItemPayload]
    payment_method: Optional[str] = "supabase-google"


class ReservePaymentPayload(BaseModel):
    position_id: int
    amount: Decimal = Field(..., gt=0)


class ReservePartialDeliveryPayload(BaseModel):
    position_id: int
    delivery_percent: int = Field(..., ge=0, le=100)


class OrderStatusPayload(BaseModel):
    status: Optional[str] = None
    payment_status: Optional[str] = None
    delivery_date: Optional[datetime] = None


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/api/auth/verify")
def api_verify_user(current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    return {"user": services.model_to_dict(current_user)}


@app.get("/api/user/profile")
def api_get_profile(current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    return services.model_to_dict(current_user)


@app.put("/api/user/profile")
def api_update_profile(
    payload: ProfileUpdatePayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)
) -> Dict[str, object]:
    if payload.name is not None:
        current_user.name = payload.name
    if payload.phone is not None:
        current_user.phone = payload.phone
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url
    db.commit()
    db.refresh(current_user)
    return services.model_to_dict(current_user)


@app.get("/api/products")
def api_list_products(db: Session = Depends(get_db)) -> List[Dict[str, object]]:
    products = services.get_products(db)
    return [services.serialize_product(product) for product in products]


@app.get("/api/products/{product_id}")
def api_get_product(product_id: int, db: Session = Depends(get_db)) -> Dict[str, object]:
    product = services.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return services.serialize_product(product)


@app.get("/api/admin/products")
def api_admin_list_products(
    db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)
) -> List[Dict[str, object]]:
    products = db.query(Product).order_by(Product.name).all()
    return [services.serialize_product(product) for product in products]


@app.post("/api/admin/products")
async def api_admin_create_product(
    sku: str = Form(...),
    name: str = Form(...),
    category: str = Form(''),
    description: Optional[str] = Form(None),
    price: Decimal = Form(...),
    lock_duration_days: int = Form(100),
    delivery_options: str = Form("standard"),
    inventory_quantity: int = Form(0),
    images: Optional[Union[UploadFile, List[UploadFile]]] = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_admin_user),
) -> Dict[str, object]:
    if isinstance(images, UploadFile):
        saved_images = [images]
    elif isinstance(images, list):
        saved_images = images
    else:
        saved_images = images or []
    try:
        product = services.create_product(
            db=db,
            sku=sku,
            name=name,
            category=category,
            description=description or "",
            price=price,
            lock_duration_days=lock_duration_days,
            delivery_options=delivery_options,
            inventory_quantity=inventory_quantity,
            images=saved_images,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return services.serialize_product(product)


@app.get("/api/admin/orders")
def api_admin_list_orders(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    return [services.model_to_dict(order, include_relationships=True) for order in orders]


@app.get("/api/admin/users")
def api_admin_list_users(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    users = db.query(UserProfile).order_by(UserProfile.created_at.desc()).all()
    return [services.model_to_dict(user, include_relationships=True) for user in users]


@app.get("/api/admin/inventory")
def api_admin_inventory(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    inventory_rows = db.query(Inventory).join(Product).order_by(Product.name).all()
    return [
        {
            **services.model_to_dict(row),
            "available_quantity": max((row.quantity or 0) - (row.reserved_quantity or 0), 0),
            "stock_health": (
                "critical"
                if (row.quantity or 0) <= 5
                else "low"
                if (row.quantity or 0) <= 10
                else "healthy"
            ),
            "product": services.serialize_product(row.product) if row.product else None,
        }
        for row in inventory_rows
    ]


@app.get("/api/admin/reserves")
def api_admin_reserves(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    reserves = db.query(ReserveVault).order_by(ReserveVault.created_at.desc()).all()
    payload = []
    for reserve in reserves:
        data = services.model_to_dict(reserve, include_relationships=True)
        data["user"] = services.model_to_dict(reserve.user) if reserve.user else None
        payload.append(data)
    return payload


@app.get("/api/admin/deliveries")
def api_admin_deliveries(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    schedules = db.query(DeliverySchedule).order_by(DeliverySchedule.scheduled_date.asc()).all()
    payload = []
    for schedule in schedules:
        data = services.model_to_dict(schedule)
        item = schedule.reserve_item
        data["reserve_item"] = services.model_to_dict(item) if item else None
        data["product"] = services.serialize_product(item.product) if item and item.product else None
        data["reserve"] = services.model_to_dict(item.reserve_vault) if item and item.reserve_vault else None
        data["customer"] = services.model_to_dict(item.reserve_vault.user) if item and item.reserve_vault and item.reserve_vault.user else None
        payload.append(data)
    return payload


@app.get("/api/admin/payments")
def api_admin_payments(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> List[Dict[str, object]]:
    payments = db.query(Payment).order_by(Payment.created_at.desc()).all()
    return [
        {
            **services.model_to_dict(payment),
            "order": services.model_to_dict(payment.order) if payment.order else None,
            "customer": services.model_to_dict(payment.order.user) if payment.order and payment.order.user else None,
        }
        for payment in payments
    ]


@app.put("/api/admin/orders/{order_id}")
def api_admin_update_order(
    order_id: int,
    payload: OrderStatusPayload,
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_admin_user),
) -> Dict[str, object]:
    order = db.query(Order).filter(Order.id == order_id).one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if payload.status is not None:
        order.status = payload.status
    if payload.payment_status is not None:
        order.payment_status = payload.payment_status
    if payload.delivery_date is not None:
        order.delivery_date = payload.delivery_date
    db.commit()
    db.refresh(order)
    return services.model_to_dict(order, include_relationships=True)


@app.put("/api/admin/products/{product_id}")
async def api_admin_update_product(
    product_id: int,
    name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price: Optional[Decimal] = Form(None),
    lock_duration_days: Optional[int] = Form(None),
    delivery_options: Optional[str] = Form(None),
    inventory_quantity: Optional[int] = Form(None),
    images: Optional[Union[UploadFile, List[UploadFile]]] = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_admin_user),
) -> Dict[str, object]:
    if isinstance(images, UploadFile):
        images = [images]
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    try:
        services.update_product(
            db=db,
            product=product,
            name=name,
            category=category,
            description=description,
            price=price,
            lock_duration_days=lock_duration_days,
            delivery_options=delivery_options,
            inventory_quantity=inventory_quantity,
            images=images,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return services.serialize_product(product)


@app.delete("/api/admin/products/{product_id}")
def api_admin_delete_product(
    product_id: int, db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)
) -> JSONResponse:
    product = db.query(Product).filter(Product.id == product_id).one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    services.delete_product(db, product)
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={})


@app.get("/api/cart")
def api_get_cart(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    cart = services.get_or_create_active_cart(db, current_user)
    return services.get_cart_summary(cart)


@app.post("/api/cart/items")
def api_add_cart_item(payload: AddCartItemPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    product = services.get_product(db, payload.product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    cart = services.get_or_create_active_cart(db, current_user)
    item = services.add_or_update_cart_item(
        db=db,
        cart=cart,
        product=product,
        quantity=payload.quantity,
        reserve_option=payload.reserve_option,
        partial_delivery=payload.partial_delivery,
        lock_duration_days=payload.lock_duration_days,
    )
    return services.model_to_dict(item)


@app.put("/api/cart/items/{item_id}")
def api_update_cart_item(item_id: int, payload: UpdateCartItemPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    cart = services.get_or_create_active_cart(db, current_user)
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    item.quantity = payload.quantity
    db.commit()
    db.refresh(item)
    return services.model_to_dict(item)


@app.delete("/api/cart/items/{item_id}")
def api_remove_cart_item(item_id: int, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> JSONResponse:
    cart = services.get_or_create_active_cart(db, current_user)
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
    db.delete(item)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={})


@app.post("/api/checkout")
def api_checkout(payload: CheckoutPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    cart = services.get_or_create_active_cart(db, current_user)

    if payload.items:
        for item_payload in payload.items:
            product_id = int(item_payload.get("product_id"))
            quantity = int(item_payload.get("quantity", 1))
            reserve_option = str(item_payload.get("reserve_option") or "purchase")
            partial_delivery = bool(item_payload.get("partial_delivery", False))
            lock_duration_days = int(item_payload.get("lock_duration_days", 100))
            product = services.get_product(db, product_id)
            if not product:
                continue
            services.add_or_update_cart_item(
                db=db,
                cart=cart,
                product=product,
                quantity=quantity,
                reserve_option=reserve_option,
                partial_delivery=partial_delivery,
                lock_duration_days=lock_duration_days,
            )

    if not cart.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    order = services.create_order_from_cart(
        db,
        current_user,
        cart,
        payment_method=payload.payment_method or "supabase-google",
        payment_intent_id=payload.payment_intent_id,
        metadata={"source": "checkout", "payment_intent_id": payload.payment_intent_id} if payload.payment_intent_id else {"source": "checkout"},
    )
    create_referral_commission_for_order(db, order)
    services.notify_user(db, current_user, "Order Confirmed", f"Your order {order.order_number} is confirmed.")
    return services.model_to_dict(order)


@app.get("/api/orders")
def api_list_orders(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> List[Dict[str, object]]:
    orders = db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc()).all()
    return [services.model_to_dict(order, include_relationships=True) for order in orders]


@app.get("/api/orders/{order_id}")
def api_get_order(order_id: int, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return services.model_to_dict(order, include_relationships=True)


@app.post("/api/reserves")
def api_create_reserve(payload: ReservePayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reserve items are required")
    vault = services.create_reserve_vault(db, current_user, [item.dict() for item in payload.items], payload.payment_method or "supabase-google")
    services.notify_user(db, current_user, "Reserve Locked", f"Your reserve vault #{vault.id} is active through {vault.locked_until.date()}.")
    services.send_email(
        current_user.email,
        "FoodVault Reserve Confirmation",
        f"<p>Your reserve vault has been created. Total reserved value: ${vault.total_value}.</p>",
    )
    return services.model_to_dict(vault, include_relationships=True)


@app.get("/api/reserves")
def api_list_reserves(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> List[Dict[str, object]]:
    reserves = (
        db.query(ReserveVault)
        .filter(ReserveVault.user_id == current_user.id, ReserveVault.status == "active")
        .order_by(ReserveVault.created_at.desc())
        .all()
    )
    return [services.model_to_dict(vault, include_relationships=True) for vault in reserves]


@app.get("/api/vault/reserves")
def api_get_vault_reserves(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> List[Dict[str, object]]:
    positions = services.get_user_reserve_positions(db, current_user)
    return [services.model_to_dict(position, include_relationships=True) for position in positions]


@app.post("/api/reserve/payment")
def api_apply_reserve_payment(payload: ReservePaymentPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    try:
        position = services.apply_reserve_payment(db, current_user, payload.position_id, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return services.model_to_dict(position, include_relationships=True)


@app.post("/api/reserve/partial-delivery")
def api_request_partial_delivery(payload: ReservePartialDeliveryPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    try:
        position = services.request_partial_delivery(db, current_user, payload.position_id, payload.delivery_percent)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return services.model_to_dict(position, include_relationships=True)


@app.get("/api/vault")
def api_get_vault(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> List[Dict[str, object]]:
    """Return active reserve vaults for the current user."""
    vaults = (
        db.query(ReserveVault)
        .filter(ReserveVault.user_id == current_user.id, ReserveVault.status == "active")
        .order_by(ReserveVault.created_at.desc())
        .all()
    )
    return [services.model_to_dict(v, include_relationships=True) for v in vaults]


@app.post("/api/vault/add")
def api_vault_add(payload: ReserveItemPayload, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    """Add an item to the user's active reserve vault (or create a new vault)."""
    product = db.query(Product).filter(Product.id == payload.product_id, Product.is_active.is_(True)).one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # find active vault
    vault = db.query(ReserveVault).filter(ReserveVault.user_id == current_user.id, ReserveVault.status == "active").order_by(ReserveVault.created_at.desc()).first()
    if not vault:
        vault = services.create_reserve_vault(db, current_user, [payload.dict()], "supabase-google")
        return services.model_to_dict(vault, include_relationships=True)

    # create reserve item and update vault
    unit_price = product.price
    total_price = unit_price * payload.quantity
    deposit_rate = 0.15 if payload.reserve_type == "deposit" else 0.20
    deposit_paid = (total_price * deposit_rate)
    from decimal import Decimal

    lock_expires_at = datetime.utcnow() + timedelta(days=int(product.lock_duration_days or 100))
    lifecycle_metadata = services.build_reserve_lifecycle_metadata(
        product=product,
        quantity=payload.quantity,
        total_value=Decimal(total_price),
        deposit_paid=Decimal(deposit_paid),
        partial_delivery=payload.partial_delivery,
        lock_expires_at=lock_expires_at,
    )

    reserve_item = ReserveItem(
        reserve_vault=vault,
        product=product,
        quantity=payload.quantity,
        unit_price=unit_price,
        deposit_paid=deposit_paid,
        reserve_type=payload.reserve_type,
        partial_delivery=payload.partial_delivery,
        delivery_split={"deposit_rate": float(deposit_rate), "partial_delivery": payload.partial_delivery},
        metadata_json=lifecycle_metadata,
        status="active_lock",
    )
    db.add(reserve_item)
    position = services.ReservePosition(
        user=current_user,
        product=product,
        reserve_vault=vault,
        reserved_quantity=payload.quantity,
        locked_price=unit_price,
        total_value=Decimal(total_price),
        deposit_paid=Decimal(deposit_paid),
        ownership_percent=max(1, int((Decimal(deposit_paid) / Decimal(total_price)) * Decimal("100"))) if total_price else 0,
        remaining_balance=max(Decimal("0.00"), Decimal(total_price) - Decimal(deposit_paid)),
        lock_expires_at=lock_expires_at,
        status="active_lock",
        metadata_json=lifecycle_metadata,
    )
    db.add(position)
    schedule = DeliverySchedule(reserve_item=reserve_item, scheduled_date=datetime.utcnow(), quantity=payload.quantity if not payload.partial_delivery else payload.quantity // 2, notes="Added to vault")
    db.add(schedule)
    inventory = product.inventory
    if not inventory:
        inventory = Inventory(product=product, quantity=0, reserved_quantity=0, incoming_quantity=0)
        db.add(inventory)
    inventory.quantity = max(inventory.quantity - payload.quantity, 0)
    inventory.reserved_quantity += payload.quantity

    vault.total_value = (vault.total_value or Decimal("0.00")) + Decimal(total_price)
    vault.upfront_paid = (vault.upfront_paid or Decimal("0.00")) + Decimal(deposit_paid)
    vault.metadata_json = {
        **(vault.metadata_json or {}),
        "reservation": {
            "lock_percent": 15,
            "ownership_percent": max(1, int((Decimal(deposit_paid) / Decimal(total_price)) * Decimal("100"))) if total_price else 0,
            "lock_duration_days": int(product.lock_duration_days or 100),
            "locked_until": lock_expires_at.isoformat(),
            "reservation_type": "inventory_lock",
            "partial_delivery_enabled": payload.partial_delivery,
        },
        "payment_events": [
            {
                "type": "deposit",
                "amount": float(deposit_paid),
                "timestamp": datetime.utcnow().isoformat(),
                "percent": max(1, int((Decimal(deposit_paid) / Decimal(total_price)) * Decimal("100"))) if total_price else 0,
            }
        ],
        "delivery": {
            "partial_delivered_percent": 0,
            "remaining_locked_percent": 100,
            "delivery_status": "partial_active" if payload.partial_delivery else "scheduled",
        },
    }
    vault.health_score = services.calculate_reserve_health_score(vault)
    db.commit()
    db.refresh(vault)
    return services.model_to_dict(vault, include_relationships=True)


@app.delete("/api/vault/remove/{item_id}")
def api_vault_remove(item_id: int, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> JSONResponse:
    item = db.query(ReserveItem).filter(ReserveItem.id == item_id).one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserve item not found")
    vault = item.reserve_vault
    if vault.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to remove this item")
    associated_positions = db.query(services.ReservePosition).filter(
        services.ReservePosition.reserve_vault_id == vault.id,
        services.ReservePosition.product_id == item.product_id,
    ).all()
    for position in associated_positions:
        db.delete(position)
    # restore inventory
    if item.product and item.product.inventory:
        item.product.inventory.reserved_quantity = max(item.product.inventory.reserved_quantity - item.quantity, 0)
        item.product.inventory.quantity = item.product.inventory.quantity + item.quantity
    db.delete(item)
    db.commit()
    return JSONResponse(status_code=200, content={"ok": True})


@app.get("/api/vault/analytics")
def api_vault_analytics(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    data = services.build_dashboard_data(db, current_user)
    # Provide a concise analytics payload
    analytics = {
        "reserve_summary": data.get("reserve_summary", {}),
        "consumption_series": data.get("consumption_series", []),
        "savings_series": data.get("savings_series", []),
        "alerts": data.get("alerts", []),
    }
    return analytics


@app.get("/api/dashboard")
def api_dashboard(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    return services.build_dashboard_data(db, current_user)


@app.get("/api/notifications")
def api_notifications(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> List[Dict[str, object]]:
    notifications = db.query(services.Notification).filter(services.Notification.user_id == current_user.id).order_by(services.Notification.created_at.desc()).all()
    return [services.model_to_dict(notification) for notification in notifications]


@app.post("/api/notifications/{notification_id}/read")
def api_read_notification(notification_id: int, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)) -> Dict[str, object]:
    notification = db.query(services.Notification).filter(services.Notification.id == notification_id, services.Notification.user_id == current_user.id).one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return services.model_to_dict(notification)


@app.get("/api/admin/analytics")
def api_admin_analytics(db: Session = Depends(get_db), current_user=Depends(auth.require_admin_user)) -> Dict[str, object]:
    return services.fetch_admin_analytics(db)


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "FoodVault backend is running", "version": "1.0"}
