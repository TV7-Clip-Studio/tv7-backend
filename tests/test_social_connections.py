from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.db.models import SocialCredential, User
from app.services import social_oauth, youtube_oauth


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "SOCIAL_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    for name in (
        "INSTAGRAM_CLIENT_ID",
        "INSTAGRAM_CLIENT_SECRET",
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
    ):
        monkeypatch.setattr(settings, name, "test-client")
    monkeypatch.setattr(
        settings, "INSTAGRAM_REDIRECT_URI", "http://localhost/api/v1/social/instagram/callback"
    )
    monkeypatch.setattr(
        settings, "TIKTOK_REDIRECT_URI", "http://localhost/api/v1/social/tiktok/callback"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["instagram", "tiktok"])
@pytest.mark.usefixtures("configured")
async def test_oauth_identity_encryption_profile_and_replay(
    async_client, auth_headers, monkeypatch, db_session, platform
):
    def transport(request):
        if request.url.path == "/v2/oauth/token/":
            return httpx.Response(
                200,
                json={
                    "access_token": "private-access",
                    "refresh_token": "private-refresh",
                    "open_id": "account-1",
                    "scope": "user.info.basic,video.publish",
                    "expires_in": 86400,
                    "refresh_expires_in": 31536000,
                },
            )
        if request.url.path == "/v2/user/info/":
            return httpx.Response(
                200,
                json={
                    "data": {"user": {"open_id": "account-1", "display_name": "Creator"}},
                    "error": {"code": "ok"},
                },
            )
        if request.url.host == "api.instagram.com":
            return httpx.Response(
                200,
                json={
                    "access_token": "short",
                    "user_id": "account-1",
                    "permissions": [
                        "instagram_business_basic",
                        "instagram_business_content_publish",
                    ],
                },
            )
        if request.url.path == "/access_token":
            return httpx.Response(
                200, json={"access_token": "private-access", "expires_in": 5184000}
            )
        return httpx.Response(200, json={"user_id": "account-1", "username": "Creator"})

    monkeypatch.setattr(
        social_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport))
    )
    started = await async_client.post(
        f"/api/v1/social/{platform}/connect",
        json={"creator_profile_id": "profile-one"},
        headers=auth_headers,
    )
    assert started.status_code == 200
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    # State cannot be used on a different provider callback.
    other = "instagram" if platform == "tiktok" else "tiktok"
    wrong = await async_client.get(
        f"/api/v1/social/{other}/callback", params={"state": state, "code": "code"}
    )
    assert wrong.status_code == 400
    callback = await async_client.get(
        f"/api/v1/social/{platform}/callback", params={"state": state, "code": "code"}
    )
    assert callback.status_code == 200
    assert "private-access" not in callback.text
    replay = await async_client.get(
        f"/api/v1/social/{platform}/callback", params={"state": state, "code": "code"}
    )
    assert replay.status_code == 400
    rows = (
        await async_client.get(
            "/api/v1/social/connections",
            params={"creator_profile_id": "profile-one"},
            headers=auth_headers,
        )
    ).json()
    item = next(row for row in rows if row["platform"] == platform)
    assert item["display_name"] == "Creator"
    assert item["publishing_ready"] is False
    assert (
        await async_client.get(
            "/api/v1/social/connections",
            params={"creator_profile_id": "other-profile"},
            headers=auth_headers,
        )
    ).json() == []
    stored = (
        await db_session.execute(
            select(SocialCredential).where(SocialCredential.id == int(item["id"].split(":")[1]))
        )
    ).scalar_one()
    assert stored.access_token_encrypted != "private-access"
    assert (
        social_oauth.cipher().decrypt(stored.access_token_encrypted.encode()) == b"private-access"
    )
    deleted = await async_client.delete(
        f"/api/v1/social/connections/{item['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_social_setup_and_auth(async_client, monkeypatch):
    monkeypatch.setattr(settings, "INSTAGRAM_CLIENT_ID", None)
    providers = (await async_client.get("/api/v1/social/providers")).json()
    assert (
        next(item for item in providers if item["platform"] == "instagram")["oauth_configured"]
        is False
    )
    assert "CLIENT_SECRET" not in str(providers)
    assert (await async_client.get("/api/v1/social/connections")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured")
async def test_missing_scope_consumes_state(async_client, auth_headers, monkeypatch):
    def transport(_request):
        return httpx.Response(200, json={"access_token": "access", "scope": "user.info.basic"})

    monkeypatch.setattr(
        social_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport))
    )
    response = await async_client.post(
        "/api/v1/social/tiktok/connect",
        headers=auth_headers,
        json={"creator_profile_id": "profile-one"},
    )
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    failed = await async_client.get(
        "/api/v1/social/tiktok/callback", params={"state": state, "code": "code"}
    )
    assert failed.status_code == 400
    assert "permissions" in failed.text
    replay = await async_client.get(
        "/api/v1/social/tiktok/callback", params={"state": state, "code": "code"}
    )
    assert "already used" in replay.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured")
async def test_profile_reconnect_cannot_steal_connection(async_client, auth_headers, monkeypatch):
    async def exchange(_platform, _code):
        return (
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": "user.info.basic,video.publish",
                "expires_in": 86400,
            },
            "isolated-account",
            "Creator",
        )

    monkeypatch.setattr(social_oauth, "_exchange", exchange)
    for profile, expected in (("profile-one", 200), ("profile-two", 400)):
        started = await async_client.post(
            "/api/v1/social/tiktok/connect",
            headers=auth_headers,
            json={"creator_profile_id": profile},
        )
        state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
        finished = await async_client.get(
            "/api/v1/social/tiktok/callback", params={"state": state, "code": "code"}
        )
        assert finished.status_code == expected
    listing = await async_client.get(
        "/api/v1/social/connections",
        headers=auth_headers,
        params={"creator_profile_id": "profile-two"},
    )
    assert listing.json() == []
    denied = await async_client.get(
        "/api/v1/social/tiktok/callback",
        params={"state": "x" * 32, "error": "access_denied"},
        headers={"Accept": "text/html"},
    )
    assert denied.status_code == 400
    assert "cancelled" in denied.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured")
@pytest.mark.parametrize("platform", ["instagram", "tiktok"])
async def test_expired_tokens_refresh_encrypted(db_session, monkeypatch, platform):
    user = User(
        email=f"refresh-{platform}@example.com", full_name="Refresh tester", password_hash="hash"
    )
    db_session.add(user)
    await db_session.commit()
    credential = SocialCredential(
        user_id=user.id,
        platform=platform,
        provider_account_id="refresh-account",
        display_name="Creator",
        creator_profile_id="refresh-profile",
        access_token_encrypted=social_oauth.cipher().encrypt(b"old-access").decode(),
        refresh_token_encrypted=(
            social_oauth.cipher().encrypt(b"old-refresh").decode() if platform == "tiktok" else None
        ),
        scope=",".join(social_oauth.SCOPES[platform]),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(credential)
    await db_session.commit()

    def transport(_request):
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "open_id": "refresh-account",
                "expires_in": 86400,
                "refresh_expires_in": 31536000,
            },
        )

    monkeypatch.setattr(
        social_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport))
    )
    assert await social_oauth.access_token_for(db_session, credential) == "fresh-access"
    assert credential.access_token_encrypted != "fresh-access"
    assert (
        social_oauth.cipher().decrypt(credential.refresh_token_encrypted.encode())
        == b"fresh-refresh"
    )
    assert await social_oauth.access_token_for(db_session, credential) == "fresh-access"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured")
async def test_cancelled_state_cannot_complete(async_client, auth_headers):
    started = await async_client.post(
        "/api/v1/social/tiktok/connect",
        headers=auth_headers,
        json={"creator_profile_id": "cancel-profile"},
    )
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    await async_client.get(
        "/api/v1/social/tiktok/callback", params={"state": state, "error": "access_denied"}
    )
    retry = await async_client.get(
        "/api/v1/social/tiktok/callback", params={"state": state, "code": "code"}
    )
    assert retry.status_code == 400
    assert "already used" in retry.text


@pytest.mark.asyncio
async def test_disconnect_is_owner_scoped(async_client, auth_headers, db_session):
    owner = User(email="another-social-owner@example.com", full_name="Other", password_hash="hash")
    db_session.add(owner)
    await db_session.commit()
    credential = SocialCredential(
        user_id=owner.id,
        platform="instagram",
        provider_account_id="other-owned-account",
        creator_profile_id="other-owned-profile",
        display_name="Other",
        access_token_encrypted="encrypted",
        scope="",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(credential)
    await db_session.commit()
    result = await async_client.delete(
        f"/api/v1/social/connections/instagram:{credential.id}", headers=auth_headers
    )
    assert result.status_code == 404
    assert await db_session.get(SocialCredential, credential.id) is not None
    malformed = await async_client.delete(
        "/api/v1/social/connections/not-valid", headers=auth_headers
    )
    assert malformed.status_code == 404
    unsupported = await async_client.delete(
        f"/api/v1/social/connections/unknown:{credential.id}", headers=auth_headers
    )
    assert unsupported.status_code == 404


@pytest.mark.asyncio
async def test_unconfigured_connect_and_https_requirement(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "TIKTOK_CLIENT_KEY", None)
    response = await async_client.post(
        "/api/v1/social/tiktok/connect",
        json={"creator_profile_id": "profile"},
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert "not configured" in response.text
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "INSTAGRAM_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "INSTAGRAM_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "INSTAGRAM_REDIRECT_URI", "http://localhost/callback")
    assert social_oauth.oauth_configured("instagram") is False


@pytest.mark.parametrize("status,payload", [(400, {}), (200, []), (200, {"error": "denied"})])
def test_provider_failures_do_not_expose_tokens(status, payload):
    with pytest.raises(social_oauth.SocialOAuthError, match="Provider failed"):
        social_oauth._checked(httpx.Response(status, json=payload), "Provider failed")


def test_token_cipher_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "SOCIAL_TOKEN_ENCRYPTION_KEYS", None)
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", None)
    with pytest.raises(social_oauth.SocialOAuthError, match="encryption"):
        social_oauth.cipher()


@pytest.mark.asyncio
async def test_registered_google_callback_alias_returns_completion(async_client):
    response = await async_client.get(
        "/admin/youtube/callback",
        params={"state": "x" * 32, "error": "access_denied"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 400
    assert "cancelled" in response.text
    assert "Refresh accounts" in response.text


@pytest.mark.asyncio
async def test_youtube_reconnect_does_not_move_profile(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())

    def google(request):
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "scope": f"{youtube_oauth.UPLOAD_SCOPE} {youtube_oauth.READ_SCOPE} {youtube_oauth.UPDATE_SCOPE}",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(
            200, json={"items": [{"id": "UCnoSilentMove", "snippet": {"title": "Owner channel"}}]}
        )

    monkeypatch.setattr(
        youtube_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(google))
    )
    for profile, expected in (
        ("original-profile", 200),
        ("another-profile", 400),
        ("original-profile", 200),
    ):
        started = await async_client.post(
            "/api/v1/social/youtube/connect",
            json={"creator_profile_id": profile},
            headers=auth_headers,
        )
        state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
        callback = await async_client.get(
            "/api/v1/social/youtube/callback", params={"state": state, "code": "code"}
        )
        assert callback.status_code == expected
    listing = await async_client.get("/api/v1/social/connections", headers=auth_headers)
    youtube = next(item for item in listing.json() if item["platform"] == "youtube")
    assert youtube["creator_profile_id"] == "original-profile"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channels", "message"),
    [
        ([], "0 channels returned"),
        ([{"id": "UCone"}, {"id": "UCtwo"}], "2 YouTube channels"),
        ([{"snippet": {"title": "Missing identity"}}], "invalid channel identity"),
    ],
)
async def test_youtube_channel_lookup_errors_are_actionable(
    async_client, auth_headers, monkeypatch, channels, message
):
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())

    def google(request):
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "scope": f"{youtube_oauth.UPLOAD_SCOPE} {youtube_oauth.READ_SCOPE} {youtube_oauth.UPDATE_SCOPE}",
                },
            )
        assert request.url.params["mine"] == "true"
        return httpx.Response(200, json={"items": channels})

    monkeypatch.setattr(
        youtube_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(google))
    )
    started = await async_client.post(
        "/api/v1/social/youtube/connect",
        json={"creator_profile_id": "test-channel-errors"},
        headers=auth_headers,
    )
    query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    assert query["prompt"] == ["select_account consent"]
    callback = await async_client.get(
        "/api/v1/social/youtube/callback", params={"state": query["state"][0], "code": "code"}
    )
    assert callback.status_code == 400
    assert message in callback.text
    assert "access_token" not in callback.text
