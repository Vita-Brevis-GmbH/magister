"""Mailversand: Graph und SMTP, ohne Netz. Das Geheimnis taucht nie in Fehlern auf."""

from __future__ import annotations

import dataclasses
import json
import smtplib
import socket
from typing import Any

import httpx
import pytest

from magister_api.mail import MailConfig, MailError, MailMessage, MailNotConfiguredError, send_mail
from magister_api.mail import sender as sender_mod

SECRET = "sehr-geheim-123"
MSG = MailMessage(to="lea@schule.ch", subject="Ihr Passwort", html="<p>Hallo</p>", text="Hallo")
GRAPH = MailConfig(
    transport="graph",
    sender="noreply@schule.ch",
    graph_tenant_id="tid",
    graph_client_id="cid",
    secret=SECRET,
)


def _graph_transport(send_status: int = 202, token_status: int = 200) -> tuple[Any, list[Any]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "login.microsoftonline.com":
            if token_status != 200:
                return httpx.Response(
                    token_status,
                    json={"error": "invalid_client", "error_description": "AADSTS7000215: bad"},
                )
            return httpx.Response(200, json={"access_token": "tok"})
        if send_status != 202:
            return httpx.Response(
                send_status, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        return httpx.Response(202)

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_graph_sends_as_the_sender_mailbox() -> None:
    transport, calls = _graph_transport()
    await send_mail(GRAPH, MSG, transport=transport)
    token, send = calls
    assert token.url.path == "/tid/oauth2/v2.0/token"
    assert send.url.path == "/v1.0/users/noreply@schule.ch/sendMail"
    assert send.headers["Authorization"] == "Bearer tok"
    body = json.loads(send.content)
    assert body["message"]["toRecipients"][0]["emailAddress"]["address"] == "lea@schule.ch"
    assert body["saveToSentItems"] is False


@pytest.mark.asyncio
async def test_graph_errors_are_readable_and_never_carry_the_secret() -> None:
    transport, _ = _graph_transport(token_status=401)
    with pytest.raises(MailError) as exc:
        await send_mail(GRAPH, MSG, transport=transport)
    assert "invalid_client" in str(exc.value)
    assert SECRET not in str(exc.value)
    transport, _ = _graph_transport(send_status=403)
    with pytest.raises(MailError, match="sendMail 403 ErrorAccessDenied"):
        await send_mail(GRAPH, MSG, transport=transport)


@pytest.mark.asyncio
async def test_incomplete_configuration_says_what_is_missing() -> None:
    with pytest.raises(MailNotConfiguredError, match="graph_client_id, mail_secret"):
        await send_mail(MailConfig(transport="graph", sender="a@b.ch", graph_tenant_id="t"), MSG)
    with pytest.raises(MailNotConfiguredError, match="mail_transport"):
        await send_mail(MailConfig(transport="off", sender=None), MSG)


class _FakeSmtp:
    instances: list[_FakeSmtp] = []

    def __init__(self, host: str, port: int, timeout: float = 0, **kw: Any) -> None:
        self.host, self.port = host, port
        self.steps: list[str] = []
        self.sent: list[Any] = []
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *a: object) -> None:
        self.steps.append("quit")

    def ehlo(self) -> None:
        self.steps.append("ehlo")

    def starttls(self, context: Any = None) -> None:
        self.steps.append("starttls")

    def login(self, user: str, password: str) -> None:
        if password != SECRET:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials")
        self.steps.append(f"login {user}")

    def send_message(self, msg: Any) -> None:
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_smtp_always_starttls_then_login_then_send(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSmtp.instances.clear()
    monkeypatch.setattr(sender_mod, "_Smtp", _FakeSmtp)
    cfg = MailConfig(
        transport="smtp",
        sender="noreply@schule.ch",
        sender_name="Magister",
        smtp_host="mail.schule.ch",
        smtp_username="noreply@schule.ch",
        secret=SECRET,
    )
    await send_mail(cfg, MSG)
    smtp = _FakeSmtp.instances[0]
    assert smtp.port == 587
    assert smtp.steps[:4] == ["ehlo", "starttls", "ehlo", "login noreply@schule.ch"]
    mime = smtp.sent[0]
    assert mime["To"] == "lea@schule.ch"
    assert mime["From"] == "Magister <noreply@schule.ch>"

    bad = dataclasses.replace(cfg, secret="falsch")
    with pytest.raises(MailError, match="authentication failed") as exc:
        await send_mail(bad, MSG)
    assert "falsch" not in str(exc.value)


class _FakeSocket:
    #: IP → Fehler beim Verbinden; fehlt die IP, gelingt die Verbindung.
    failures: dict[str, OSError] = {}
    tried: list[str] = []

    def __init__(self, family: int, kind: int, proto: int) -> None:
        self.family = family

    def settimeout(self, timeout: float) -> None:
        pass

    def connect(self, addr: tuple[Any, ...]) -> None:
        _FakeSocket.tried.append(addr[0])
        if addr[0] in _FakeSocket.failures:
            raise _FakeSocket.failures[addr[0]]

    def close(self) -> None:
        pass


def _fake_resolver(monkeypatch: pytest.MonkeyPatch, failures: dict[str, OSError]) -> None:
    infos = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 587, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587)),
    ]
    monkeypatch.setattr(sender_mod.socket, "getaddrinfo", lambda *a, **kw: list(infos))
    monkeypatch.setattr(sender_mod.socket, "socket", _FakeSocket)
    _FakeSocket.failures = failures
    _FakeSocket.tried = []


def test_smtp_connect_prefers_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_resolver(monkeypatch, {"2001:db8::1": OSError(101, "Network is unreachable")})
    sock = sender_mod._connect("mail.schule.ch", 587, 1.0)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(sock, _FakeSocket)
    assert _FakeSocket.tried == ["192.0.2.1"]


def test_smtp_connect_failure_names_every_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """Früher stand nur der erste Fehler (IPv6: unreachable) da — der falsche."""
    _fake_resolver(
        monkeypatch,
        {
            "2001:db8::1": OSError(101, "Network is unreachable"),
            "192.0.2.1": TimeoutError("timed out"),
        },
    )
    with pytest.raises(OSError) as exc:
        sender_mod._connect("mail.schule.ch", 587, 1.0)  # pyright: ignore[reportPrivateUsage]
    text = str(exc.value)
    assert "192.0.2.1: timed out" in text
    assert "2001:db8::1: Network is unreachable" in text
    assert text.index("192.0.2.1") < text.index("2001:db8::1")
    assert "port 587" in text


@pytest.mark.asyncio
async def test_smtp_unreachable_is_a_readable_mail_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_resolver(
        monkeypatch,
        {
            "2001:db8::1": OSError(101, "Network is unreachable"),
            "192.0.2.1": OSError(111, "Connection refused"),
        },
    )
    cfg = MailConfig(transport="smtp", sender="noreply@schule.ch", smtp_host="mail.schule.ch")
    with pytest.raises(MailError, match=r"smtp: no connection to mail.schule.ch:587"):
        await send_mail(cfg, MSG)
