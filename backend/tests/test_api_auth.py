from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import roles, verify_token
from app.config import Settings
from app.main import app, rate_limit
from app.models import AppUser
from app.services.exports import export_available


@pytest.fixture
def client():
    app.dependency_overrides[rate_limit] = lambda: None
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_and_capabilities_are_honest(client):
    assert client.get("/health/live").json() == {"status": "alive"}
    capabilities = {
        c["capability"]: c for c in client.get("/api/v1/capabilities").json()
    }
    assert capabilities["ai_extraction"]["available"] is False
    assert capabilities["glb_3d_tiles"]["available"] is export_available()


def test_protected_routes_reject_missing_tokens(client):
    assert client.get("/api/v1/parcels").status_code == 401
    assert client.post("/api/v1/units", json={}).status_code == 401


def test_openapi_contains_validated_contracts_without_fake_login(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/auth/me" in schema["paths"]
    assert "/api/v1/auth/login" not in schema["paths"]
    assert "GeometryCreate" in schema["components"]["schemas"]
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_verified_jwt_checks_signature_issuer_audience_and_expiry(monkeypatch):
    import app.auth as auth

    private = ec.generate_private_key(ec.SECP256R1())
    user_id = uuid4()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "user_metadata": {"role": "admin"},
    }

    class Key:
        key = private.public_key()

    class Client:
        def get_signing_key_from_jwt(self, token):
            return Key()

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(supabase_url="https://example.supabase.co"),
    )
    monkeypatch.setattr(auth, "jwks_client", lambda: Client())
    assert verify_token(jwt.encode(claims, private, algorithm="ES256")) == user_id
    for change in [
        {"aud": "wrong"},
        {"iss": "https://attacker.invalid"},
        {"exp": now - timedelta(minutes=1)},
    ]:
        with pytest.raises(HTTPException) as exc:
            verify_token(jwt.encode(claims | change, private, algorithm="ES256"))
        assert exc.value.status_code == 401
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(HTTPException):
        verify_token(jwt.encode(claims, other_key, algorithm="ES256"))


def test_rbac_uses_server_managed_role():
    user = AppUser(id=uuid4(), role="viewer", active=True)
    with pytest.raises(HTTPException) as exc:
        roles("officer")(user)
    assert exc.value.status_code == 403


def test_production_rejects_insecure_configuration():
    with pytest.raises(ValueError):
        Settings(environment="production")


def test_object_storage_blocks_path_traversal(monkeypatch, tmp_path):
    import app.storage as storage

    monkeypatch.setattr(
        storage, "get_settings", lambda: Settings(storage_root=tmp_path)
    )
    with pytest.raises(ValueError):
        storage.local_path("../outside")
    key, digest = storage.put_bytes(b"original evidence bytes")
    assert storage.read_bytes(key) == b"original evidence bytes"
    assert len(digest) == 64


def test_rate_limiter_fails_closed_and_reports_retry(monkeypatch):
    from redis.exceptions import ConnectionError
    from starlette.requests import Request

    import app.main as main

    request = Request({"type": "http", "client": ("127.0.0.1", 1), "headers": []})

    class Unavailable:
        def eval(self, *args):
            raise ConnectionError("private redis details")

    monkeypatch.setattr(main, "redis_client", lambda: Unavailable())
    with pytest.raises(HTTPException) as exc:
        main.rate_limit(request)
    assert exc.value.status_code == 503

    class Limited:
        def eval(self, *args):
            return main.get_settings().requests_per_minute + 1

    monkeypatch.setattr(main, "redis_client", lambda: Limited())
    with pytest.raises(HTTPException) as exc:
        main.rate_limit(request)
    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "60"}


def test_cors_rejects_unlisted_browser_origin(client):
    response = client.options(
        "/api/v1/parcels",
        headers={
            "Origin": "https://unlisted.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
