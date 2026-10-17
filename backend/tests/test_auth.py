"""Clerk-mode identity: tenancy comes from the verified token, not the request body."""
from urllib.parse import quote

from starlette.requests import Request

from reliefnet import auth
from reliefnet.config import get_settings


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "query_string": b""})


async def _identity(monkeypatch, claims: dict, headers: dict[str, str]):
    monkeypatch.setattr(get_settings(), "auth_mode", "clerk")

    async def fake_verify(token: str) -> dict:
        return claims

    seen: dict = {}

    async def fake_member(user, display_name=None):
        seen["display_name"] = display_name
        return user

    monkeypatch.setattr(auth, "_verify_clerk", fake_verify)
    monkeypatch.setattr(auth, "ensure_member", fake_member)
    user = await auth.current_user(_request({"authorization": "Bearer t", **headers}))
    return user, seen


async def test_org_without_slug_uses_org_id_and_decodes_names(monkeypatch):
    user, seen = await _identity(
        monkeypatch,
        {"sub": "user_1", "o": {"id": "org_2AbC", "rol": "admin"}},
        {"x-org-name": quote("सहयोग NGO"), "x-user-name": quote("आशा देवी")},
    )
    assert user.org == "org_2abc"
    assert user.role == "admin"
    assert user.name == "आशा देवी"
    assert seen["display_name"] == "सहयोग NGO"


async def test_member_role_is_volunteer_and_slug_wins(monkeypatch):
    user, _ = await _identity(
        monkeypatch,
        {"sub": "user_2", "o": {"id": "org_9", "slg": "red-cross", "rol": "member"}},
        {},
    )
    assert user.org == "red_cross"
    assert user.role == "volunteer"
