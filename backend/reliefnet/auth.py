"""Authentication and tenancy.

The org (and so the FalkorDB graph) always comes from the verified identity,
never from the request body.

AUTH_MODE=dev   - pick a seeded user on the login screen; identity travels in
                  X-Dev-* headers. For local demos only.
AUTH_MODE=clerk - verify the Clerk session JWT. The active Clerk Organization's
                  slug selects the graph; its role selects permissions."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request

from . import orgs
from .config import get_settings
from .db import org_graph_name, query

ROLE_RANK = {"volunteer": 0, "coordinator": 1, "admin": 2}


@dataclass
class User:
    id: str
    name: str
    org: str
    role: str
    team: str | None = None

    def at_least(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[role]


_jwks: jwt.PyJWKClient | None = None
_seen: dict[tuple[str, str], tuple[float, str | None]] = {}


def _jwks_client() -> jwt.PyJWKClient:
    global _jwks
    if _jwks is None:
        url = get_settings().clerk_jwks_url
        if not url:
            raise HTTPException(500, "CLERK_JWKS_URL is not configured")
        _jwks = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks


def _map_role(raw: str | None) -> str:
    r = (raw or "").removeprefix("org:")
    if r == "admin":
        return "admin"
    if r in ("coordinator", "manager"):
        return "coordinator"
    return "volunteer"


async def _verify_clerk(token: str) -> dict:
    s = get_settings()
    try:
        key = await asyncio.to_thread(_jwks_client().get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=s.clerk_issuer or None,
            options={"verify_iss": bool(s.clerk_issuer), "verify_aud": False},
            leeway=10,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid session token: {e}") from e
    parties = [p.strip() for p in s.clerk_authorized_parties.split(",") if p.strip()]
    if parties and claims.get("azp") and claims["azp"] not in parties:
        raise HTTPException(401, "token was issued for another origin")
    return claims


async def ensure_member(user: User, display_name: str | None = None) -> User:
    """Create the org graph on first sight and attach the user to it."""
    from .seed import ensure_org_schema, seed_org

    key = (user.org, user.id)
    hit = _seen.get(key)
    if hit and time.monotonic() - hit[0] < 15:
        user.team = hit[1]
        return user

    if not await orgs.get(user.org):
        await seed_org(user.org, display_name or user.org.replace("_", " ").title())
    else:
        await ensure_org_schema(user.org)
    rows = await query(
        org_graph_name(user.org),
        "MERGE (v:Volunteer {id:$id}) ON CREATE SET v.created_at = timestamp()"
        " SET v.name = $name, v.role = $role"
        " WITH v OPTIONAL MATCH (v)-[:MEMBER_OF]->(t:Team) RETURN t.name AS team",
        {"id": user.id, "name": user.name, "role": user.role},
    )
    user.team = rows[0]["team"] if rows else None
    _seen[key] = (time.monotonic(), user.team)
    return user


def forget(org: str, uid: str) -> None:
    _seen.pop((org, uid), None)


async def current_user(request: Request) -> User:
    s = get_settings()
    if s.auth_mode == "dev":
        h = request.headers
        q = request.query_params
        uid = h.get("x-dev-user") or q.get("dev_user")
        org = h.get("x-dev-org") or q.get("dev_org")
        if not uid or not org:
            raise HTTPException(401, "sign in required")
        o = await orgs.get(org)
        if not o:
            raise HTTPException(403, f"unknown org {org}")
        role = h.get("x-dev-role") or q.get("dev_role") or "volunteer"
        name = h.get("x-dev-name") or q.get("dev_name") or uid
        user = User(id=uid, name=name, org=org, role=role if role in ROLE_RANK else "volunteer")
    else:
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
        if not token:
            raise HTTPException(401, "sign in required")
        claims = await _verify_clerk(token)
        o = claims.get("o") or {}
        slug = o.get("slg") or claims.get("org_slug")
        if not slug:
            raise HTTPException(403, "select an organisation first")
        slug = orgs.normalize_slug(slug)
        user = User(
            id=claims["sub"],
            name=request.headers.get("x-user-name") or claims.get("name") or claims["sub"],
            org=slug,
            role=_map_role(o.get("rol") or claims.get("org_role")),
        )
    return await ensure_member(user)


def require(role: str):
    async def dep(user: User = Depends(current_user)) -> User:
        if not user.at_least(role):
            raise HTTPException(403, f"{role} role required")
        return user

    return dep


async def dev_users() -> list[dict]:
    """Seeded identities for the dev login screen."""
    out = []
    for o in await orgs.all_orgs():
        slug = o["slug"]
        out.append({"id": f"coord_{slug}", "name": "Shift Coordinator", "org": slug, "org_name": o["name"],
                    "role": "coordinator", "team": None})
        out.append({"id": f"admin_{slug}", "name": "Org Admin", "org": slug, "org_name": o["name"],
                    "role": "admin", "team": None})
        vols = await query(
            org_graph_name(slug),
            "MATCH (v:Volunteer)-[:MEMBER_OF]->(t:Team) WHERE v.role = 'volunteer'"
            " RETURN v.id AS id, v.name AS name, t.name AS team ORDER BY t.name",
            readonly=True,
        )
        for v in vols:
            out.append({**v, "org": slug, "org_name": o["name"], "role": "volunteer"})
    return out

