"""Authentication helpers for the context MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth.providers.google import GoogleProvider


@dataclass
class OAuthProxySettings:
    """Settings required to instantiate an OAuthProxy."""

    upstream_authorization_endpoint: str
    upstream_token_endpoint: str
    upstream_client_id: str
    upstream_client_secret: str
    base_url: str
    jwks_uri: str
    issuer: str
    audience: str
    redirect_path: Optional[str] = None
    allowed_client_redirect_uris: Optional[List[str]] = None
    forward_pkce: bool = True
    token_endpoint_auth_method: Optional[str] = None
    extra_authorize_params: Dict[str, str] = field(default_factory=dict)
    extra_token_params: Dict[str, str] = field(default_factory=dict)
    required_scopes: Optional[List[str]] = None
    valid_scopes: Optional[List[str]] = None


@dataclass
class GoogleAuthSettings:
    """Settings required to instantiate a GoogleProvider."""

    client_id: str
    client_secret: str
    base_url: str
    redirect_path: Optional[str] = None
    required_scopes: Optional[List[str]] = None
    timeout_seconds: Optional[int] = None
    allowed_client_redirect_uris: Optional[List[str]] = None


def build_oauth_proxy(settings: OAuthProxySettings) -> OAuthProxy:
    """Create an OAuthProxy instance wired for the configured provider."""

    verifier_kwargs: Dict[str, Any] = {
        "jwks_uri": settings.jwks_uri,
        "issuer": settings.issuer,
        "audience": settings.audience,
    }
    if settings.required_scopes:
        verifier_kwargs["required_scopes"] = settings.required_scopes

    verifier = JWTVerifier(**verifier_kwargs)

    proxy_kwargs: Dict[str, Any] = {
        "token_verifier": verifier,
        "base_url": settings.base_url,
    }

    if settings.redirect_path:
        proxy_kwargs["redirect_path"] = settings.redirect_path
    if settings.allowed_client_redirect_uris is not None:
        proxy_kwargs["allowed_client_redirect_uris"] = (
            settings.allowed_client_redirect_uris
        )
    if settings.valid_scopes is not None:
        proxy_kwargs["valid_scopes"] = settings.valid_scopes
    if not settings.forward_pkce:
        proxy_kwargs["forward_pkce"] = False
    if settings.token_endpoint_auth_method:
        proxy_kwargs["token_endpoint_auth_method"] = settings.token_endpoint_auth_method
    if settings.extra_authorize_params:
        proxy_kwargs["extra_authorize_params"] = settings.extra_authorize_params
    if settings.extra_token_params:
        proxy_kwargs["extra_token_params"] = settings.extra_token_params

    return OAuthProxy(
        upstream_authorization_endpoint=settings.upstream_authorization_endpoint,
        upstream_token_endpoint=settings.upstream_token_endpoint,
        upstream_client_id=settings.upstream_client_id,
        upstream_client_secret=settings.upstream_client_secret,
        **proxy_kwargs,
    )


def build_google_provider(settings: GoogleAuthSettings) -> GoogleProvider:
    """Create a GoogleProvider instance configured for the context server."""

    provider_kwargs: Dict[str, Any] = {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "base_url": settings.base_url,
    }
    if settings.redirect_path:
        provider_kwargs["redirect_path"] = settings.redirect_path
    if settings.required_scopes:
        provider_kwargs["required_scopes"] = settings.required_scopes
    if settings.timeout_seconds is not None:
        provider_kwargs["timeout_seconds"] = settings.timeout_seconds
    if settings.allowed_client_redirect_uris:
        provider_kwargs["allowed_client_redirect_uris"] = settings.allowed_client_redirect_uris

    return GoogleProvider(**provider_kwargs)
