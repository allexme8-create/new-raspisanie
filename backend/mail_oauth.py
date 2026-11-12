"""OAuth for SMTP: fixed provider endpoints, encrypted tokens and one-use admin-bound state."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import smtplib
import ssl
import time
from urllib.parse import urlencode, urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken

PROVIDERS = {
    "yandex": {"authorize": "https://oauth.yandex.ru/authorize", "token": "https://oauth.yandex.ru/token", "scope": "mail:smtp", "domains": {"yandex.ru", "yandex.com", "ya.ru", "yandex.by", "yandex.kz"}, "host": "smtp.yandex.ru"},
    # Mail.ru uses mail.imap for IMAP/SMTP OAuth; this may require provider approval.
    "mailru": {"authorize": "https://oauth.mail.ru/login", "token": "https://oauth.mail.ru/token", "scope": "userinfo mail.imap", "domains": {"mail.ru", "list.ru", "inbox.ru", "bk.ru"}, "host": "smtp.mail.ru"},
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cipher() -> Fernet:
    try:
        return Fernet(os.environ.get("MAIL_OAUTH_ENCRYPTION_KEY", "").encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Задайте MAIL_OAUTH_ENCRYPTION_KEY в секретах сервера; инструкция — в DEPLOY.md.") from exc


def config(provider: str) -> tuple[dict, str, str, str]:
    info = PROVIDERS.get(provider)
    if not info:
        raise RuntimeError("Неизвестный почтовый сервис.")
    prefix = "YANDEX" if provider == "yandex" else "MAILRU"
    client_id = os.environ.get(prefix + "_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get(prefix + "_OAUTH_CLIENT_SECRET", "").strip()
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    try:
        parts = urlsplit(base)
        valid = parts.scheme == "https" and parts.hostname and not (parts.path or parts.query or parts.fragment or parts.username or parts.password)
    except ValueError:
        valid = False
    if not client_id or not client_secret or not valid:
        raise RuntimeError(f"Настройте {prefix}_OAUTH_CLIENT_ID, {prefix}_OAUTH_CLIENT_SECRET и PUBLIC_BASE_URL на сервере.")
    cipher()
    return info, client_id, client_secret, base + "/mail-oauth/callback"


def authorize_url(provider: str, state: str, sender: str) -> str:
    info, client_id, _, redirect_uri = config(provider)
    if sender.rsplit("@", 1)[-1].lower() not in info["domains"]:
        raise RuntimeError("Адрес отправителя не соответствует выбранному провайдеру.")
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": info["scope"], "state": state}
    return info["authorize"] + "?" + urlencode(params)


def tokens_request(provider: str, values: dict) -> dict:
    info, client_id, client_secret, redirect_uri = config(provider)
    try:
        if provider == "mailru" and values.get("grant_type") == "authorization_code":
            data = {**values, "redirect_uri": redirect_uri}
            auth = (client_id, client_secret)
        elif provider == "mailru":
            data = {**values, "client_id": client_id}
            auth = None
        else:
            data = {**values, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}
            auth = None
        response = requests.post(info["token"], data=data, auth=auth, timeout=15, allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise ValueError("OAuth endpoint returned a non-success response")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise ValueError("missing token")
        expires_in = int(data.get("expires_in", 3600))
        if expires_in <= 0:
            raise ValueError("invalid expiry")
        return {"access_token": data["access_token"], "refresh_token": data.get("refresh_token"), "expires_at": int(time.time()) + expires_in}
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("OAuth-сервер не принял запрос. Проверьте настройки приложения и разрешения.") from exc


def smtp_auth(client, sender: str, access_token: str) -> None:
    client.ehlo()
    payload = base64.b64encode(f"user={sender}\x01auth=Bearer {access_token}\x01\x01".encode()).decode("ascii")
    code, _ = client.docmd("AUTH", "XOAUTH2 " + payload)
    if code != 235:
        raise RuntimeError("Не удалось авторизоваться на SMTP. Проверьте адрес и права приложения.")


def verify_smtp(provider: str, sender: str, token: str) -> None:
    try:
        with smtplib.SMTP_SSL(PROVIDERS[provider]["host"], 465, timeout=15, context=ssl.create_default_context()) as client:
            smtp_auth(client, sender, token)
    except Exception as exc:
        raise RuntimeError("Не удалось проверить SMTP-доступ. Проверьте адрес, права приложения и доступность SMTP-сервера.") from exc


def encrypted(data: dict) -> str:
    return cipher().encrypt(json.dumps(data).encode()).decode()


def decrypted(blob: str) -> dict:
    try:
        return json.loads(cipher().decrypt(blob.encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise RuntimeError("Не удалось прочитать OAuth-токен. Проверьте ключ шифрования или подключите почту заново.") from exc


def access_for_store(store) -> tuple[str, str] | None:
    # SQLite serializes refresh, including across workers; avoid rotated-token races.
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT provider,sender,tokens FROM mail_oauth WHERE id=1").fetchone()
        if not row:
            return None
        data = decrypted(row["tokens"])
        if data["expires_at"] <= int(time.time()) + 60:
            if not data.get("refresh_token"):
                raise RuntimeError("Срок OAuth-доступа истёк. Подключите почту заново.")
            fresh = tokens_request(row["provider"], {"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
            fresh["refresh_token"] = fresh.get("refresh_token") or data["refresh_token"]
            db.execute("UPDATE mail_oauth SET tokens=? WHERE id=1", (encrypted(fresh),))
            data = fresh
        return row["sender"], data["access_token"]
