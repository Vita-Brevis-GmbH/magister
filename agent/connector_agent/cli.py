"""``magister-connector`` — Kommandozeile des Agenten (ADR-0014).

Vier Befehle:

* ``enroll``    — Einmal-Token einlösen, Schlüssel lokal erzeugen, Zustand anlegen
* ``run``       — Abrufbetrieb (das macht der Dienst)
* ``check``     — Konfiguration, Rechte und Erreichbarkeit prüfen, ohne etwas zu tun
* ``uninstall`` — bei der Plattform abmelden, Schlüssel löschen, Programm entfernen

``check`` ist der Befehl für die Abnahme beim Kunden: er sagt, ob der Kanal zur
Plattform steht (Name, Port, Zertifikat), ob die Rechte stimmen und ob das AD
das Dienstkonto annimmt — bevor irgendwer auf einen Passwort-Reset wartet.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from connector_agent.adenv import apply_missing, service_environment
from connector_agent.config import (
    DEFAULT_CONFIG_PATH,
    AgentConfig,
    ConfigError,
    assert_permissions,
    load_secrets,
)
from connector_agent.diagnose import ip_endpoint_hint, probe_channel
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

    # Vor allem anderen: passt das Zertifikat noch zum Schlüssel? Eine
    # Erneuerung, die mitten im Wechsel abgebrochen ist, hinterlässt ein Paar,
    # das nicht zusammengehört — und dann wäre die erste Meldung ein
    # OpenSSL-Fehler, den niemand mit „Erneuerung" verbindet.
    from connector_agent.renewal import RenewalError, recover_if_broken

    try:
        recover_if_broken(config)
    except RenewalError as exc:
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
    hint = ip_endpoint_hint(config.endpoint)
    if hint:
        # Kein eigener Fehler: hat das Zertifikat ausnahmsweise die IP als
        # Namen, geht es. Ob es geht, sagt die Kanal-Zeile unten.
        sys.stdout.write(f"              WARNUNG — {hint}\n")
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
        problems += _report_certificate(config)

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

    probe = probe_channel(config)
    if probe.ok:
        sys.stdout.write(f"Kanal:        ok — {probe.message}\n")
    else:
        sys.stdout.write(f"Kanal:        FEHLER — {probe.message}\n")
        problems += 1

    problems += _report_ad()

    if problems:
        sys.stdout.write(f"\n{problems} Punkt(e) offen.\n")
        return 1
    sys.stdout.write("\nAlles bereit.\n")
    return 0


def _report_certificate(config: AgentConfig) -> int:
    """Restlaufzeit des Zertifikats melden. Rückgabe: Anzahl Probleme.

    Steht im ``check``, weil es die Frage ist, die man bei einem Agenten, der
    „seit gestern nichts mehr tut" als erste stellt — und weil ein Zertifikat,
    das in drei Tagen abläuft, ein Befund ist und keine Randnotiz.
    """
    from connector_agent.renewal import RENEW_BEFORE_DAYS, RenewalError, days_until_expiry

    try:
        days = days_until_expiry(config.cert_path)
    except RenewalError as exc:
        sys.stdout.write(f"Zertifikat:   FEHLER — {exc}\n")
        return 1
    if days < 0:
        sys.stdout.write(
            f"Zertifikat:   ABGELAUFEN seit {abs(days):.0f} Tagen. Der Agent kommt "
            "nicht mehr durch; in der Konsole widerrufen und neu anmelden.\n"
        )
        return 1
    if days <= RENEW_BEFORE_DAYS:
        # Kein Problem, sondern der vorgesehene Zustand: der Dienst erneuert
        # in diesem Fenster selbständig. Ein "FEHLER" hier würde eine Abnahme
        # unnötig durchfallen lassen.
        sys.stdout.write(
            f"Zertifikat:   läuft in {days:.0f} Tagen ab — der Dienst erneuert "
            "selbständig (stündlicher Versuch, solange es nicht klappt).\n"
        )
        return 0
    sys.stdout.write(f"Zertifikat:   ok, {days:.0f} Tage Restlaufzeit\n")
    return 0


#: Was die Ursachen-Codes aus ``magister_api.ad.errors`` beim Kunden heissen.
#: Die Codes tragen weder Host noch DN noch Passwort; die Sätze auch nicht.
AD_REASONS: dict[str, str] = {
    "ad_config": (
        "AD-Zugang unvollständig: Domänencontroller, Bind-DN oder Passwort fehlen "
        "(MAGISTER_AD_DCS, MAGISTER_AD_BIND_DN, MAGISTER_AD_BIND_PASSWORD)."
    ),
    "ad_unreachable": (
        "Kein Domänencontroller auf Port 636 erreichbar. Namen in MAGISTER_AD_DCS "
        "und die Firewall zwischen diesem Server und den DCs prüfen."
    ),
    "ad_tls": (
        "LDAPS zum Domänencontroller gescheitert. Hat der DC ein Zertifikat für "
        "LDAPS, und vertraut dieser Server der ausstellenden CA?"
    ),
    "ad_timeout": "Der Domänencontroller antwortet nicht rechtzeitig.",
    "ad_auth": (
        "Der Domänencontroller hat das Dienstkonto abgewiesen: Bind-DN oder "
        "Passwort falsch, Konto gesperrt oder abgelaufen."
    ),
}


def _report_ad() -> int:
    """Bindet sich einmal mit dem Dienstkonto ans AD. Rückgabe: Anzahl Probleme.

    Erst damit beantwortet ``check`` die Frage, die bei der Abnahme zählt:
    kommt ein Passwort-Reset bis ins AD? Kanal und Zertifikat allein sagen
    nur, dass der Auftrag beim Agenten ankommt.
    """
    service = service_environment()
    if service is not None:
        taken = apply_missing(service)
        sys.stdout.write(f"AD-Umgebung:  {service.source}, {len(service.values)} Wert(e)\n")
        if not taken and service.values:
            sys.stdout.write("              (von Hand gesetzte Werte dieser Sitzung gehen vor)\n")
    else:
        sys.stdout.write(
            "AD-Umgebung:  keine Dienst-Umgebung gefunden — es gilt nur diese Sitzung\n"
        )
    ad = build_ad_client()
    if ad is None:
        sys.stdout.write("AD:           FEHLER — AD-Schicht nicht ladbar (siehe oben)\n")
        return 1
    probe = getattr(ad, "probe_service_connection_detailed", None)
    if probe is None:  # pragma: no cover — ältere AD-Schicht im Paket
        sys.stdout.write("AD:           nicht geprüft — die AD-Schicht kennt den Test nicht\n")
        return 0
    ok, reason = asyncio.run(probe())
    if ok:
        sys.stdout.write("AD:           ok — LDAPS-Bind mit dem Dienstkonto gelungen\n")
        return 0
    text = AD_REASONS.get(reason, f"Bind gescheitert ({reason}).")
    sys.stdout.write(f"AD:           FEHLER — {text}\n")
    return 1


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
    from pydantic import ValidationError

    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        # Nur die Feldnamen: der Text eines Validierungsfehlers enthält den
        # eingegebenen Wert, und einer davon ist das Bind-Passwort.
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        sys.stderr.write(f"AD-Konfiguration ungültig in: {', '.join(fields)}\n")
        return None
    except Exception as exc:  # pragma: no cover — alles andere, ohne den Text
        # Dieselbe Vorsicht: nur der Typ. Der Dienst (winservice) erwartet
        # hier `None` und meldet dann selbst, was zu tun ist.
        sys.stderr.write(f"AD-Konfiguration nicht ladbar ({type(exc).__name__}).\n")
        return None
    return AdClient(settings)


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Abmelden, Zugang löschen, Programm entfernen — in dieser Reihenfolge."""
    from connector_agent import uninstall as un

    if not un.is_admin():
        sys.stderr.write(
            "Dafür braucht es Administratorrechte (Zustandsverzeichnis, Dienst, "
            "Installationsprogramm). Nichts verändert.\n"
            "Windows: Eingabeaufforderung per Rechtsklick „Als Administrator "
            "ausführen“. Linux: mit sudo.\n"
        )
        return 1

    config_path = Path(args.config)
    try:
        config: AgentConfig | None = _load(args)
    except ConfigError as exc:
        config = None
        sys.stderr.write(
            f"Konfiguration nicht lesbar ({exc}). Abmelden bei der Plattform geht so "
            "nicht; das Programm wird trotzdem entfernt.\n"
        )

    if not args.ja:
        sys.stdout.write(
            "Der Agent wird bei der Plattform abgemeldet, sein Schlüssel gelöscht und\n"
            "das Programm entfernt. Danach braucht es für diesen Server ein neues\n"
            "Einmal-Token aus der Konsole.\n"
            "Fortfahren? Mit 'ja' bestätigen: "
        )
        sys.stdout.flush()
        if sys.stdin.readline().strip().lower() != "ja":
            sys.stdout.write("Abgebrochen. Nichts verändert.\n")
            return 1

    report = un.UninstallReport()
    report.service = un.stop_service()
    sys.stdout.write(f"Dienst:        {report.service}\n")

    if config is not None:
        secrets = load_secrets(config)
        if args.ohne_plattform:
            report.deregister_problem = "übersprungen (--ohne-plattform)"
        elif secrets is None:
            report.deregister_problem = "nicht angemeldet — nichts abzumelden"
            report.deregistered = True
        else:
            try:
                un.deregister(config, secrets)
                report.deregistered = True
            except un.DeregisterError as exc:
                report.deregister_problem = str(exc)
        if report.deregistered and not report.deregister_problem:
            sys.stdout.write("Plattform:     abgemeldet (in der Konsole jetzt widerrufen)\n")
        elif report.deregistered:
            sys.stdout.write(f"Plattform:     {report.deregister_problem}\n")
        else:
            sys.stdout.write(
                f"Plattform:     NICHT abgemeldet — {report.deregister_problem}\n"
                "               In der Konsole beim Kunden unter „AD-Connector“ den Agenten\n"
                "               widerrufen. Der Schlüssel wird trotzdem gelöscht; benutzen\n"
                "               kann die Anmeldung danach niemand mehr.\n"
            )
        report.removed = un.wipe(config, everything=args.alles, config_path=config_path)
        for path in report.removed:
            sys.stdout.write(f"Gelöscht:      {path}\n")
        if not args.alles:
            sys.stdout.write(
                f"Behalten:      Konfiguration und Protokoll in {config.state_dir} "
                "(mit --alles auch diese)\n"
            )

    report.package = un.remove_package(keep=args.paket_behalten)
    sys.stdout.write(f"Programm:      {report.package}\n")
    return 0 if report.deregistered or args.ohne_plattform else 2


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

    uninstall_cmd = sub.add_parser(
        "uninstall", help="Bei der Plattform abmelden, Schlüssel löschen, Programm entfernen"
    )
    uninstall_cmd.add_argument("--ja", action="store_true", help="ohne Rückfrage")
    uninstall_cmd.add_argument(
        "--alles",
        action="store_true",
        help="auch Konfiguration und Protokoll löschen (das ganze Zustandsverzeichnis)",
    )
    uninstall_cmd.add_argument(
        "--ohne-plattform",
        action="store_true",
        help="nicht bei der Plattform abmelden (dann in der Konsole widerrufen)",
    )
    uninstall_cmd.add_argument(
        "--paket-behalten",
        action="store_true",
        help="nur abmelden und Schlüssel löschen, das Programm bleibt installiert",
    )
    uninstall_cmd.set_defaults(func=cmd_uninstall)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
