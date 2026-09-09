"""``magister-connector`` — Kommandozeile des Agenten (ADR-0014).

Drei Befehle:

* ``enroll``  — Einmal-Token einlösen, Schlüssel lokal erzeugen, Zustand anlegen
* ``run``     — Abrufbetrieb (das macht der Dienst)
* ``check``   — Konfiguration, Rechte und Erreichbarkeit prüfen, ohne etwas zu tun

``check`` ist der Befehl für die Abnahme beim Kunden: er sagt, ob der Port
offen ist, ob die Rechte stimmen und ob das AD antwortet — bevor irgendwer auf
einen Passwort-Reset wartet.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from connector_agent.config import (
    DEFAULT_CONFIG_PATH,
    AgentConfig,
    ConfigError,
    assert_permissions,
    load_secrets,
)
from connector_agent.enrollment import EnrollmentFailedError, enroll

VERSION = "0.1.0"

logger = logging.getLogger("connector_agent")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _load(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig.from_file(Path(args.config))


def cmd_enroll(args: argparse.Namespace) -> int:
    config = _load(args)
    token = args.token
    if not token:
        # Über stdin, damit das Token nicht in der Shell-History und nicht in
        # der Prozessliste landet.
        sys.stderr.write("Einmal-Token: ")
        sys.stderr.flush()
        token = sys.stdin.readline().strip()
    if not token:
        sys.stderr.write("Kein Token angegeben.\n")
        return 2
    try:
        result = enroll(config, token=token, agent_version=VERSION)
    except (EnrollmentFailedError, ConfigError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(
        "Anmeldung erfolgreich.\n"
        f"  Agent-Id:            {result.agent_id}\n"
        f"  SPKI-Fingerprint:    {result.spki_sha256}\n"
        f"  Zertifikat gültig bis {result.certificate_not_after}\n\n"
        "Diesen Fingerprint mit der Anzeige in der Konsole vergleichen. Weichen\n"
        "sie ab, hat sich jemand anders mit dem Token angemeldet.\n"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _load(args)
    try:
        assert_permissions(config)
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    secrets = load_secrets(config)
    if secrets is None:
        sys.stderr.write(
            "Der Agent ist nicht angemeldet. Zuerst 'magister-connector enroll' "
            "mit dem Einmal-Token aus der Konsole ausführen.\n"
        )
        return 1

    from connector_agent.runner import AdExecutor, Runner

    ad = build_ad_client()
    if ad is None:
        return 1
    runner = Runner(
        config=config,
        secrets=secrets,
        executor=AdExecutor(ad),
        guardrails=config.guardrails,
        agent_version=VERSION,
    )
    logger.info(
        "Agent startet. Endpunkt %s, %d erlaubte OU(s), %d geschützte Gruppe(n).",
        config.endpoint,
        len(config.allowed_ous),
        len(config.protected_groups),
    )
    if not config.allowed_ous:
        logger.warning(
            "Es ist keine OU-Allowlist konfiguriert. Verzeichnisaufträge werden "
            "abgelehnt, bis eine steht — das ist Absicht, nicht ein Fehler."
        )
    asyncio.run(runner.serve_forever())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Abnahme-Befehl: sagt, was noch fehlt, ohne etwas zu verändern."""
    problems = 0
    try:
        config = _load(args)
    except ConfigError as exc:
        sys.stderr.write(f"Konfiguration: {exc}\n")
        return 1
    sys.stdout.write(f"Endpunkt:     {config.endpoint}\n")
    sys.stdout.write(f"Zustand:      {config.state_dir}\n")

    try:
        assert_permissions(config)
        sys.stdout.write("Rechte:       ok\n")
    except ConfigError as exc:
        sys.stdout.write(f"Rechte:       FEHLER — {exc}\n")
        problems += 1

    secrets = None
    try:
        secrets = load_secrets(config)
    except (OSError, KeyError, ValueError) as exc:
        sys.stdout.write(f"Anmeldung:    FEHLER — Zustand unlesbar ({exc})\n")
        problems += 1
    if secrets is None:
        sys.stdout.write("Anmeldung:    fehlt — 'enroll' ausführen\n")
        problems += 1
    else:
        sys.stdout.write(f"Anmeldung:    ok, SPKI {secrets.spki_sha256}\n")

    if config.allowed_ous:
        sys.stdout.write(f"OU-Allowlist: {len(config.allowed_ous)} Eintrag/Einträge\n")
    else:
        sys.stdout.write("OU-Allowlist: LEER — Verzeichnisaufträge werden abgelehnt\n")
        problems += 1

    if not config.ca_bundle.exists():
        sys.stdout.write(
            f"CA-Bundle:    fehlt ({config.ca_bundle}) — es gilt der System-Truststore\n"
        )
    else:
        sys.stdout.write("CA-Bundle:    ok\n")

    sys.stdout.write(
        "\nErreichbarkeit von TCP 46200 bitte zusätzlich von diesem Server aus prüfen:\n"
        f"  curl -sv --cacert {config.ca_bundle} {config.endpoint}/connector/jobs\n"
        "Ohne Client-Zertifikat MUSS der Handshake scheitern — das ist der Beweis,\n"
        "dass der Kanal nicht offen steht.\n"
    )
    if problems:
        sys.stdout.write(f"\n{problems} Punkt(e) offen.\n")
        return 1
    sys.stdout.write("\nAlles bereit.\n")
    return 0


def build_ad_client() -> object | None:
    """AD-Client aus ``magister_api.ad`` bauen.

    Öffentlich, weil ihn zwei Einsprungpunkte brauchen: der ``run``-Befehl von
    Hand und der Windows-Dienst (:mod:`connector_agent.winservice`).

    Bewusst derselbe Code wie im direkten Pfad: siebzehn LDAP-Operationen ein
    zweites Mal zu schreiben hiesse, zwei Stände zu pflegen, von denen einer
    schlechter getestet ist. Die Zugangsdaten kommen aus der Umgebung
    (``MAGISTER_AD_*``), also aus der Dienst-Konfiguration beim Kunden — nie
    von der Plattform.
    """
    try:
        from magister_api.ad.client import AdClient
        from magister_api.config import Settings
    except ImportError:
        sys.stderr.write(
            "magister_api ist nicht installiert. Der Agent benutzt dessen "
            "AD-Schicht; im Paket ist sie enthalten.\n"
        )
        return None
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:  # pragma: no cover — Pydantic-Validierungsfehler
        sys.stderr.write(f"AD-Konfiguration unvollständig: {exc}\n")
        return None
    return AdClient(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="magister-connector", description=__doc__)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Pfad zur Konfigurationsdatei (Vorgabe: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    enroll_cmd = sub.add_parser("enroll", help="Einmal-Token einlösen")
    enroll_cmd.add_argument(
        "--token",
        default="",
        help="Einmal-Token. Ohne diese Option wird es von stdin gelesen, "
        "damit es nicht in der Prozessliste steht.",
    )
    enroll_cmd.set_defaults(func=cmd_enroll)

    run_cmd = sub.add_parser("run", help="Abrufbetrieb (der Dienst)")
    run_cmd.set_defaults(func=cmd_run)

    check_cmd = sub.add_parser("check", help="Konfiguration und Rechte prüfen")
    check_cmd.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
