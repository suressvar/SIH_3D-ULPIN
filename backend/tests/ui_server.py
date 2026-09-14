"""Isolated browser-test host. Never imported by the application or deployed.
Uses a local signed JWT issuer; normal JWT verification and RBAC remain enabled.
Redis limiter and broker transport are substituted only in this test harness.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

if (
    os.getenv("ASTRA_UI_TEST") != "1"
    or os.getenv("ENVIRONMENT") != "test"
    or not os.getenv("DATABASE_URL", "").endswith("/astra_ui_test")
):
    raise RuntimeError(
        "UI test host requires explicit opt-in and dedicated astra_ui_test database"
    )

import demo_controls

from app.db import get_session
from app.main import app, rate_limit
from app.models import AppUser, ProcessingJob
from app.worker import run_job

app.include_router(demo_controls.router, prefix="/api/v1")

key = ec.generate_private_key(ec.SECP256R1())
public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
public.update({"kid": "isolated-browser-test", "use": "sig", "alg": "ES256"})
tokens = {}
with get_session() as db, db.begin():
    for role in ["surveyor", "officer", "viewer", "admin"]:
        subject = uuid5(NAMESPACE_URL, "astra-ui-test-" + role)
        user = db.get(AppUser, subject)
        if not user:
            db.add(AppUser(id=subject, role=role, active=True))
        tokens[role] = jwt.encode(
            {
                "sub": str(subject),
                "aud": "authenticated",
                "iss": "http://127.0.0.1:8011/auth/v1",
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(hours=4),
            },
            key,
            algorithm="ES256",
            headers={"kid": public["kid"]},
        )
output = Path("data/ui-test")
output.mkdir(parents=True, exist_ok=True)
(output / "sessions.json").write_text(json.dumps(tokens), encoding="utf-8")

# Local-only credentials. This module's explicit test/database guard is mandatory.
credential_path = output / "demo-credentials.json"
if not credential_path.exists():
    accounts = {}
    for role in ("officer", "surveyor"):
        password = secrets.token_urlsafe(15)
        salt = secrets.token_hex(16)
        accounts[f"{role}@astra.test"] = {
            "role": role,
            "salt": salt,
            "hash": hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
            ).hex(),
            "password": password,
        }
    credential_path.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
accounts = json.loads(credential_path.read_text(encoding="utf-8"))
login_attempts = []
login_lock = threading.Lock()


class DemoLogin(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


@app.get("/api/v1/auth/demo-config")
def demo_config():
    return {"enabled": True, "label": "Local demo sign-in"}


@app.post("/api/v1/auth/demo-login")
def demo_login(credentials: DemoLogin):
    with login_lock:
        now = time.monotonic()
        login_attempts[:] = [t for t in login_attempts if now - t < 60]
        if len(login_attempts) >= 20:
            raise HTTPException(429, "Too many sign-in attempts. Wait one minute.")
        login_attempts.append(now)
    account = accounts.get(credentials.email.strip().lower())
    salt = bytes.fromhex(account["salt"]) if account else bytes(16)
    digest = hashlib.scrypt(
        credentials.password.encode(), salt=salt, n=16384, r=8, p=1
    ).hex()
    if not account or not hmac.compare_digest(digest, account["hash"]):
        raise HTTPException(401, "Incorrect email or password")
    subject = uuid5(NAMESPACE_URL, "astra-ui-test-" + account["role"])
    with get_session() as db:
        member = db.get(AppUser, subject)
        if not member or not member.active:
            raise HTTPException(403, "Account is inactive")
    token = jwt.encode(
        {
            "sub": str(subject),
            "aud": "authenticated",
            "iss": "http://127.0.0.1:8011/auth/v1",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=4),
        },
        key,
        algorithm="ES256",
        headers={"kid": public["kid"]},
    )
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/v1/.well-known/jwks.json")
def keys():
    return {"keys": [public]}


def test_limiter():
    return None


app.dependency_overrides[rate_limit] = test_limiter


def jobs():
    while True:
        if demo_controls.running:
            time.sleep(0.4)
            continue
        with get_session() as db:
            ids = list(
                db.scalars(
                    select(ProcessingJob.id)
                    .where(ProcessingJob.status == "QUEUED")
                    .order_by(ProcessingJob.created_at)
                    .limit(5)
                )
            )
        for identity in ids:
            run_job(str(identity))
        time.sleep(0.4)


threading.Thread(target=jobs, daemon=True).start()
