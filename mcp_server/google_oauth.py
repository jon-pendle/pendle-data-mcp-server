"""
Google OAuth provider for MCP server, backed by Firestore.

Flow:
1. MCP client → /authorize → redirect to Google consent
2. Google → /google/callback → verify user, store auth code → redirect to client
3. MCP client → /token → exchange code for access/refresh tokens (stored in Firestore)
4. MCP client → /mcp (Bearer token) → load_access_token() verifies from Firestore

All tokens (auth codes, access tokens, refresh tokens) and registered clients
are persisted in Firestore collection "mcp_oauth".
"""

import os
import time
import secrets
import logging
import hashlib
from urllib.parse import urlencode

import httpx
from google.cloud import firestore
from starlette.requests import Request
from starlette.responses import RedirectResponse, PlainTextResponse

from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizationCode,
    RefreshToken,
    AccessToken,
    AuthorizeError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger("pendle_mcp")

# ── Google OAuth config ──────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Our server's public URL (for Google callback redirect_uri)
SERVER_BASE_URL = os.environ.get("MCP_SERVER_BASE_URL", "")

# Allowed email domains (comma-separated). Empty = allow all.
_domains = os.environ.get("OAUTH_ALLOWED_DOMAINS", "")
ALLOWED_DOMAINS = [d.strip() for d in _domains.split(",") if d.strip()]

# Token lifetimes (seconds)
ACCESS_TOKEN_TTL = 3600          # 1 hour
REFRESH_TOKEN_TTL = 86400 * 30   # 30 days
AUTH_CODE_TTL = 600              # 10 minutes

# Firestore config
_GCP_PROJECT = os.environ.get("GCP_PROJECT", "pendle-data")
_FIRESTORE_DB = os.environ.get("FIRESTORE_DB", "mcp-oauth")
_COLLECTION = "mcp_oauth"


def _hash(value: str) -> str:
    """SHA-256 hash for use as Firestore document ID. Never store tokens in plain text."""
    return hashlib.sha256(value.encode()).hexdigest()


def _get_db() -> firestore.AsyncClient:
    """Lazy Firestore client (created once per process)."""
    if not hasattr(_get_db, "_client"):
        _get_db._client = firestore.AsyncClient(project=_GCP_PROJECT, database=_FIRESTORE_DB)
    return _get_db._client


class GoogleOAuthProvider:
    """MCP OAuth Authorization Server backed by Google login + Firestore storage.

    Firestore documents (all under collection "mcp_oauth"):
      clients/{client_id}          — registered MCP clients
      auth_codes/{hash(code)}      — authorization codes (short-lived)
      access_tokens/{hash(token)}  — access tokens
      refresh_tokens/{hash(token)} — refresh tokens
      pending_auth/{state}         — pending Google auth flows (short-lived)
    """

    def _col(self, subcollection: str):
        return _get_db().collection(_COLLECTION).document("store").collection(subcollection)

    # ── Client registration ──────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        doc = await self._col("clients").document(client_id).get()
        if not doc.exists:
            return None
        return OAuthClientInformationFull(**doc.to_dict()["data"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self._col("clients").document(client_info.client_id).set({
            "data": client_info.model_dump(mode="json"),
            "created_at": time.time(),
        })
        logger.info(f"Registered OAuth client: {client_info.client_id}")

    # ── Authorization (redirect to Google) ───────────────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Store pending auth context in Firestore, then redirect to Google."""

        google_state = secrets.token_urlsafe(32)

        # Persist pending auth so /google/callback can retrieve it
        await self._col("pending_auth").document(google_state).set({
            "client_id": client.client_id,
            "params": params.model_dump(mode="json"),
            "created_at": time.time(),
        })

        google_params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": f"{SERVER_BASE_URL}/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": google_state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(google_params)}"

    # ── Google callback (mounted as custom_route) ────────────────

    async def handle_google_callback(self, request: Request):
        """Handle Google's redirect, verify user, issue our auth code."""

        error = request.query_params.get("error")
        if error:
            return PlainTextResponse(f"Google auth error: {error}", status_code=400)

        google_code = request.query_params.get("code")
        google_state = request.query_params.get("state")
        if not google_code or not google_state:
            return PlainTextResponse("Missing code or state", status_code=400)

        # Load and delete pending auth (one-time use)
        pending_ref = self._col("pending_auth").document(google_state)
        pending_doc = await pending_ref.get()
        if not pending_doc.exists:
            return PlainTextResponse("Invalid or expired state", status_code=400)
        pending = pending_doc.to_dict()
        await pending_ref.delete()

        # Reconstruct client and params
        client = await self.get_client(pending["client_id"])
        if not client:
            return PlainTextResponse("Unknown client", status_code=400)
        params = AuthorizationParams(**pending["params"])

        # Exchange Google code for Google token + user info
        email = await self._verify_google_user(google_code)
        if email is None:
            return PlainTextResponse("Google verification failed", status_code=502)

        # Check allowed domains
        domain = email.split("@")[-1] if "@" in email else ""
        if ALLOWED_DOMAINS and domain not in ALLOWED_DOMAINS:
            logger.warning(f"OAuth denied: {email} (domain {domain} not allowed)")
            return PlainTextResponse(f"Access denied for {email}", status_code=403)

        logger.info(f"Google OAuth verified: {email}")

        # Generate our authorization code and store in Firestore
        code = secrets.token_urlsafe(32)
        await self._col("auth_codes").document(_hash(code)).set({
            "code": code,
            "scopes": params.scopes or [],
            "expires_at": time.time() + AUTH_CODE_TTL,
            "client_id": client.client_id,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "email": email,
        })

        # Redirect back to MCP client
        redirect_url = construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )
        return RedirectResponse(redirect_url, status_code=302)

    async def _verify_google_user(self, google_code: str) -> str | None:
        """Exchange Google auth code for token, return email or None."""
        try:
            async with httpx.AsyncClient() as http:
                token_resp = await http.post(GOOGLE_TOKEN_URL, data={
                    "code": google_code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": f"{SERVER_BASE_URL}/google/callback",
                    "grant_type": "authorization_code",
                })
                if token_resp.status_code != 200:
                    logger.error(f"Google token exchange failed: {token_resp.text}")
                    return None

                access_token = token_resp.json().get("access_token")
                userinfo_resp = await http.get(GOOGLE_USERINFO_URL, headers={
                    "Authorization": f"Bearer {access_token}",
                })
                if userinfo_resp.status_code != 200:
                    logger.error(f"Google userinfo failed: {userinfo_resp.text}")
                    return None

                return userinfo_resp.json().get("email")
        except Exception as e:
            logger.error(f"Google verification error: {e}")
            return None

    # ── Authorization code ───────────────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        doc_id = _hash(authorization_code)
        doc = await self._col("auth_codes").document(doc_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        if data["client_id"] != client.client_id:
            return None
        if time.time() > data["expires_at"]:
            await self._col("auth_codes").document(doc_id).delete()
            return None

        return AuthorizationCode(
            code=data["code"],
            scopes=data["scopes"],
            expires_at=data["expires_at"],
            client_id=data["client_id"],
            code_challenge=data["code_challenge"],
            redirect_uri=data["redirect_uri"],
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Load email from auth code before deleting it
        auth_code_doc = await self._col("auth_codes").document(_hash(authorization_code.code)).get()
        email = auth_code_doc.to_dict().get("email", "") if auth_code_doc.exists else ""

        # Delete auth code (one-time use)
        await self._col("auth_codes").document(_hash(authorization_code.code)).delete()

        # Generate tokens
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = time.time()
        scopes = authorization_code.scopes

        # Store both in Firestore — include email so load_access_token can surface user identity
        await self._col("access_tokens").document(_hash(access)).set({
            "token": access,
            "client_id": client.client_id,
            "scopes": scopes,
            "expires_at": now + ACCESS_TOKEN_TTL,
            "created_at": now,
            "email": email,
        })
        await self._col("refresh_tokens").document(_hash(refresh)).set({
            "token": refresh,
            "client_id": client.client_id,
            "scopes": scopes,
            "expires_at": now + REFRESH_TOKEN_TTL,
            "created_at": now,
            "email": email,
        })

        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    # ── Refresh token ────────────────────────────────────────────

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        doc_id = _hash(refresh_token)
        doc = await self._col("refresh_tokens").document(doc_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        if data["client_id"] != client.client_id:
            return None
        if data.get("expires_at") and time.time() > data["expires_at"]:
            await self._col("refresh_tokens").document(doc_id).delete()
            return None

        return RefreshToken(
            token=data["token"],
            client_id=data["client_id"],
            scopes=data["scopes"],
            expires_at=int(data["expires_at"]) if data.get("expires_at") else None,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        # Load email from old refresh token before rotating
        old_ref = self._col("refresh_tokens").document(_hash(refresh_token.token))
        old_doc = await old_ref.get()
        email = old_doc.to_dict().get("email", "") if old_doc.exists else ""

        # Delete old refresh token (rotation)
        await old_ref.delete()

        # Generate new tokens
        access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        now = time.time()
        effective_scopes = scopes or refresh_token.scopes

        await self._col("access_tokens").document(_hash(access)).set({
            "token": access,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": now + ACCESS_TOKEN_TTL,
            "created_at": now,
            "email": email,
        })
        await self._col("refresh_tokens").document(_hash(new_refresh)).set({
            "token": new_refresh,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": now + REFRESH_TOKEN_TTL,
            "created_at": now,
            "email": email,
        })

        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes) if effective_scopes else None,
        )

    # ── Access token verification ────────────────────────────────

    async def load_access_token(self, token: str) -> AccessToken | None:
        doc_id = _hash(token)
        doc = await self._col("access_tokens").document(doc_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        if data.get("expires_at") and time.time() > data["expires_at"]:
            await self._col("access_tokens").document(doc_id).delete()
            return None

        # Surface user identity into the request context so tools can read it
        email = data.get("email", "")
        if email:
            from .server import current_user_email
            current_user_email.set(email)

        return AccessToken(
            token=data["token"],
            client_id=data["client_id"],
            scopes=data["scopes"],
            expires_at=int(data["expires_at"]) if data.get("expires_at") else None,
        )

    # ── Revocation ───────────────────────────────────────────────

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            await self._col("access_tokens").document(_hash(token.token)).delete()
        elif isinstance(token, RefreshToken):
            await self._col("refresh_tokens").document(_hash(token.token)).delete()
        logger.info(f"Revoked token: ...{token.token[-8:]}")
