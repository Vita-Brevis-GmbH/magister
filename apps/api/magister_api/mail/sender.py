"""Eine Mail versenden — über SMTP (STARTTLS/TLS) oder Microsoft Graph.

Graph ist der Weg für Microsoft 365: Microsoft schaltet SMTP mit Benutzername
und Passwort ab. Die App-Registrierung braucht die Anwendungsberechtigung
``Mail.Send``, beschränkt (Application Access Policy bzw. RBAC for
Applications) auf das Absender-Postfach.

Fehlertexte nennen nie das Geheimnis; sie gehen ins Versandprotokoll und in
die Oberfläche.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Protocol

import httpx
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_LOGIN = "https://login.microsoftonline.com"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
#: Je Schritt (Verbindung, STARTTLS, Anmeldung, Senden). Kurz, weil der
#: Versand einer Testmail im Abgleich läuft und dieser sonst stehen bliebe.
_SMTP_TIMEOUT = 15


class MailError(RuntimeError):
    """Versand fehlgeschlagen. ``str(exc)`` ist für Menschen lesbar."""


class MailNotConfiguredError(MailError):
    """Kein Mailversand eingerichtet (oder unvollständig)."""


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class MailConfig:
    transport: str  # "off" | "smtp" | "graph"
    sender: str | None
    sender_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str = "starttls"
    smtp_username: str | None = None
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    secret: str | None = None

    def missing(self) -> list[str]:
        """Was fehlt, damit versendet werden kann (leer = bereit)."""
        if self.transport == "off":
            return ["mail_transport"]
        need: dict[str, Any] = {"mail_from": self.sender}
        if self.transport == "smtp":
            need["smtp_host"] = self.smtp_host
            if self.smtp_username:
                need["mail_secret"] = self.secret
        elif self.transport == "graph":
            need |= {
                "graph_tenant_id": self.graph_tenant_id,
                "graph_client_id": self.graph_client_id,
                "mail_secret": self.secret,
            }
        return [k for k, v in need.items() if not v]


class _Settings(Protocol):
    @property
    def mail_transport(self) -> str: ...
    @property
    def mail_from(self) -> str | None: ...
    @property
    def mail_from_name(self) -> str | None: ...
    @property
    def smtp_host(self) -> str | None: ...
    @property
    def smtp_port(self) -> int | None: ...
    @property
    def smtp_security(self) -> str: ...
    @property
    def smtp_username(self) -> str | None: ...
    @property
    def graph_tenant_id(self) -> str | None: ...
    @property
    def graph_client_id(self) -> str | None: ...
    @property
    def mail_secret(self) -> str | None: ...


def mail_config_from(eff: _Settings) -> MailConfig:
    """Aus den wirksamen Einstellungen (``EffectiveAppSettings``)."""
    return MailConfig(
        transport=eff.mail_transport or "off",
        sender=eff.mail_from,
        sender_name=eff.mail_from_name,
        smtp_host=eff.smtp_host,
        smtp_port=eff.smtp_port,
        smtp_security=eff.smtp_security or "starttls",
        smtp_username=eff.smtp_username,
        graph_tenant_id=eff.graph_tenant_id,
        graph_client_id=eff.graph_client_id,
        secret=eff.mail_secret,
    )


async def send_mail(
    config: MailConfig,
    message: MailMessage,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Versenden oder :class:`MailError` werfen. ``transport`` nur für Tests (Graph)."""
    missing = config.missing()
    if missing:
        raise MailNotConfiguredError("mail not configured: " + ", ".join(missing))
    if config.transport == "smtp":
        await run_in_threadpool(_send_smtp, config, message)
    else:
        await _send_graph(config, message, transport=transport)


# --- SMTP --------------------------------------------------------------------


def _mime(config: MailConfig, message: MailMessage) -> EmailMessage:
    assert config.sender is not None
    mime = EmailMessage()
    mime["From"] = (
        formataddr((config.sender_name, config.sender)) if config.sender_name else config.sender
    )
    mime["To"] = str(Address(addr_spec=message.to))
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=config.sender.split("@", 1)[-1])
    mime.set_content(message.text)
    mime.add_alternative(message.html, subtype="html")
    return mime


class _ConnectError(OSError):
    """Keine der Adressen des Servers erreichbar. Die Meldung nennt jede."""


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """Mit dem SMTP-Server verbinden — IPv4 zuerst, jede Adresse der Reihe nach.

    ``socket.create_connection`` nimmt die Reihenfolge des Resolvers (meist
    IPv6 zuerst) und meldet, wenn alles scheitert, nur den *ersten* Fehler.
    Ein Container ohne IPv6-Route zeigt dann "Network is unreachable", auch
    wenn das eigentliche Problem der gesperrte Port über IPv4 ist. Hier steht
    am Ende jede Adresse mit ihrem Fehler in der Meldung.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise _ConnectError(f"name not resolvable: {host}") from exc
    infos.sort(key=lambda info: 0 if info[0] == socket.AF_INET else 1)
    errors: list[str] = []
    seen: set[str] = set()
    for family, kind, proto, _canon, addr in infos:
        ip = str(addr[0])
        if ip in seen:
            continue
        seen.add(ip)
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(addr)
        except OSError as exc:
            sock.close()
            reason = "timed out" if isinstance(exc, TimeoutError) else exc.strerror or str(exc)
            errors.append(f"{ip}: {reason}")
            continue
        return sock
    hint = (
        f" — outbound port {port} blocked (firewall/hoster)? Alternatively Microsoft Graph (HTTPS)"
        if errors
        else ""
    )
    raise _ConnectError(f"no connection to {host}:{port} ({'; '.join(errors)}){hint}")


class _Smtp(smtplib.SMTP):
    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return _connect(host, port, timeout)


class _SmtpSsl(smtplib.SMTP_SSL):
    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        sock = _connect(host, port, timeout)
        return self.context.wrap_socket(sock, server_hostname=host)


def _send_smtp(config: MailConfig, message: MailMessage) -> None:
    assert config.smtp_host is not None
    context = ssl.create_default_context()
    implicit = config.smtp_security == "tls"
    port = config.smtp_port or (465 if implicit else 587)
    try:
        if implicit:
            client: smtplib.SMTP = _SmtpSsl(
                config.smtp_host, port, timeout=_SMTP_TIMEOUT, context=context
            )
        else:
            client = _Smtp(config.smtp_host, port, timeout=_SMTP_TIMEOUT)
        with client:
            if not implicit:
                client.ehlo()
                # Ohne STARTTLS wird nicht gesendet — kein Klartext.
                client.starttls(context=context)
                client.ehlo()
            if config.smtp_username:
                client.login(config.smtp_username, config.secret or "")
            client.send_message(_mime(config, message))
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("smtp: authentication failed") from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise MailError("smtp: server does not offer STARTTLS") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError("smtp: recipient refused") from exc
    except _ConnectError as exc:
        raise MailError(f"smtp: {exc}") from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"smtp: {type(exc).__name__}: {_first_line(exc)}") from exc


# --- Microsoft Graph -----------------------------------------------------------


async def _send_graph(
    config: MailConfig, message: MailMessage, *, transport: httpx.AsyncBaseTransport | None
) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as http:
        token = await _graph_token(http, config)
        body = {
            "message": {
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": message.html},
                "toRecipients": [{"emailAddress": {"address": message.to}}],
            },
            "saveToSentItems": False,
        }
        try:
            r = await http.post(
                f"{_GRAPH}/users/{config.sender}/sendMail",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise MailError(f"graph: {type(exc).__name__}") from exc
        if r.status_code != 202:
            raise MailError(f"graph: sendMail {r.status_code} {_graph_error(r)}")


async def _graph_token(http: httpx.AsyncClient, config: MailConfig) -> str:
    try:
        r = await http.post(
            f"{_LOGIN}/{config.graph_tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.graph_client_id or "",
                "client_secret": config.secret or "",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    except httpx.HTTPError as exc:
        raise MailError(f"graph: token {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise MailError(f"graph: token {r.status_code} {_graph_error(r)}")
    token = r.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise MailError("graph: no access token")
    return token


def _graph_error(r: httpx.Response) -> str:
    """Nur Code und erste Zeile der Fehlermeldung — nie Header oder Token."""
    try:
        data = r.json()
    except ValueError:
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        return f"{err.get('code', '')}: {_first_line(err.get('message', ''))}".strip()
    if isinstance(err, str):
        # Token-Endpunkt: {"error": "invalid_client", "error_description": "AADSTS…"}
        desc = data.get("error_description", "")
        return f"{err}: {_first_line(desc)[:200]}".strip()
    return ""


def _first_line(value: object) -> str:
    return (str(value).strip().splitlines() or [""])[0][:300]
