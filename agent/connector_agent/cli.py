"""``magister-connector`` — Kommandozeile des Agenten (ADR-0014).

Der Agent läuft **auf dem Domänencontroller**, als LocalSystem, und bindet sich
als Maschinenkonto des DC per Kerberos ans AD. Eingestellt wird er im Cockpit;
auf dem DC steht nur der Weg zur Plattform.

Vier Befehle:

* ``enroll``    — Endpunkt festhalten, Einmal-Token einlösen, Schlüssel lokal
                  erzeugen, Konfiguration holen, Dienst starten
* ``run``       — Abrufbetrieb (das macht der Dienst)
* ``check``     — Kanal, Anmeldung, Konfiguration aus dem Cockpit und AD prüfen,
                  ohne etwas zu verändern
* ``uninstall`` — bei der Plattform abmelden, Schlüssel löschen, Programm entfernen
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from connector_agent import remote as remote_cfg
from connector_agent.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_STATE_DIR,
    AgentConfig,
    AgentSecrets,
    ConfigError,
    assert_permissions,
    ensure_state_dir,
    load_secrets,
    write_local_config,
)
from connector_agent.diagnose import ip_endpoint_hint, probe_channel
from connector_agent.enrollment import EnrollmentFailedError, enroll

if TYPE_CHECKING:
    from connector_agent.runner import Runner

VERSION = "0.2.0"

logger = logging.getLogger("connector_agent")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _load(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig.from_file(Path(args.config))


def _prepare_local_config(args: argparse.Namespace) -> AgentConfig:
    """Lokale Konfiguration für ``enroll``: aus ``--endpoint`` anlegen oder lesen."""
    path = Path(args.config)
    if not args.endpoint:
        return AgentConfig.from_file(path)
    if path.exists():
        existing = AgentConfig.from_file(path)
        if existing.secrets_path.exists():
            raise ConfigError(
                f"In {existing.state_dir} liegt bereits eine Anmeldung. Zum Neuanmelden erst "
                "'magister-connector uninstall --paket-behalten' ausführen."
            )
    state_dir = path.parent if path.parent != Path() else DEFAULT_STATE_DIR
    ca_target: Path | None = None
    if args.ca:
        ensure_state_dir(state_dir)
        ca_target = state_dir / "platform-ca.pem"
        shutil.copyfile(args.ca, ca_target)
    write_local_config(path, endpoint=args.endpoint, state_dir=state_dir, ca_bundle=ca_target)
    return AgentConfig.from_file(path)


def cmd_enroll(args: argparse.Namespace) -> int:
    try:
        config = _prepare_local_config(args)
    except (ConfigError, OSError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
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
        "sie ab, hat sich jemand anders mit dem Token angemeldet.\n\n"
    )
    secrets = load_secrets(config)
    if secrets is not None:
        try:
            remote, raw = remote_cfg.fetch_sync(config, secrets)
            remote_cfg.save_cache(config, raw)
            sys.stdout.write(f"{remote_cfg.describe(remote)}\n")
            if not remote.allowed_ous:
                sys.stdout.write(
                    "Noch keine OU freigegeben — im Cockpit beim Kunden unter „AD-Connector“\n"
                    "eintragen. Bis dahin lehnt der Agent Verzeichnisaufträge ab.\n"
                )
        except Exception as exc:
            sys.stdout.write(f"Konfiguration noch nicht geholt ({exc}); der Dienst holt sie.\n")
    if not args.ohne_start:
        from connector_agent.uninstall import start_service

        sys.stdout.write(f"Dienst:              {start_service()}\n")
    return 0


def initial_remote(config: AgentConfig, secrets: AgentSecrets) -> remote_cfg.RemoteConfig:
    """Konfiguration für den Start: frisch aus dem Cockpit, sonst die zuletzt geholte.

    Ohne beides startet der Agent nicht — ohne Freigabe gäbe es ohnehin nichts
    zu tun, und ohne bekannten DC nichts, wogegen er arbeiten könnte.
    """
    try:
        remote, raw = remote_cfg.fetch_sync(config, secrets)
    except Exception as exc:
        cached = remote_cfg.load_cache(config)
        if cached is None:
            raise remote_cfg.RemoteConfigError(
                f"Konfiguration aus dem Cockpit nicht geholt ({exc}), und es liegt keine "
                "frühere Fassung vor."
            ) from exc
        logger.warning(
            "Konfiguration aus dem Cockpit nicht geholt (%s) — es gilt die zuletzt geholte.", exc
        )
        return cached
    remote_cfg.save_cache(config, raw)
    return remote


def build_runner(config: AgentConfig, secrets: AgentSecrets) -> Runner:
    """Runner mit Konfiguration aus dem Cockpit — für ``run`` und den Windows-Dienst.

    Wirft :class:`remote_cfg.RemoteConfigError` oder ``ConfigError`` mit einem
    Satz, der sagt, was zu tun ist.
    """
    from connector_agent.runner import AdExecutor, Runner

    remote = initial_remote(config, secrets)
    for dn, reason in remote.refused_ous:
        logger.warning("OU-Freigabe aus dem Cockpit verworfen (%s): %s", reason, dn)
    ad = build_ad_client(remote)
    if ad is None:
        raise ConfigError("AD-Zugang aus der Konfiguration des Cockpits nicht baubar.")

    def factory(fresh: remote_cfg.RemoteConfig) -> AdExecutor | None:
        client = build_ad_client(fresh)
        return AdExecutor(client) if client is not None else None

    logger.info("Agent startet. Endpunkt %s. %s", config.endpoint, remote_cfg.describe(remote))
    if not remote.allowed_ous:
        logger.warning(
            "Im Cockpit ist keine OU freigegeben. Verzeichnisaufträge werden abgelehnt, "
            "bis eine steht — das ist Absicht, nicht ein Fehler."
        )
    return Runner(
        config=config,
        secrets=secrets,
        executor=AdExecutor(ad),
        guardrails=remote.guardrails,
        agent_version=VERSION,
        remote=remote,
        executor_factory=factory,
    )


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

    try:
        runner = build_runner(config, secrets)
    except (remote_cfg.RemoteConfigError, ConfigError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    asyncio.run(runner.serve_forever())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Abnahme-Befehl: sagt, was noch fehlt, ohne etwas zu verändern."""
    problems = 0
    try:
        config = _load(args)
    except ConfigError as exc:
        sys.stderr.write(
            f"Konfiguration: {exc}\nZuerst 'magister-connector enroll --endpoint …' ausführen.\n"
        )
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

    remote: remote_cfg.RemoteConfig | None = None
    if secrets is not None:
        try:
            remote, _raw = remote_cfg.fetch_sync(config, secrets)
            sys.stdout.write(f"Cockpit:      ok — Konfiguration {remote.revision or '-'}\n")
        except Exception as exc:
            remote = remote_cfg.load_cache(config)
            suffix = " — es gilt die zuletzt geholte" if remote is not None else ""
            sys.stdout.write(f"Cockpit:      FEHLER — {exc}{suffix}\n")
            problems += 1
    if remote is not None:
        problems += _report_remote(remote)
        problems += _report_ad(remote)
    else:
        sys.stdout.write("AD:           nicht geprüft — keine Konfiguration aus dem Cockpit\n")
        problems += 1

    if problems:
        sys.stdout.write(f"\n{problems} Punkt(e) offen.\n")
        return 1
    sys.stdout.write("\nAlles bereit.\n")
    return 0


def _report_remote(remote: remote_cfg.RemoteConfig) -> int:
    problems = 0
    if remote.allowed_ous:
        sys.stdout.write(f"OU-Freigabe:  {len(remote.allowed_ous)} OU(s) aus dem Cockpit\n")
    else:
        sys.stdout.write(
            "OU-Freigabe:  LEER — im Cockpit beim Kunden unter „AD-Connector“ eintragen;\n"
            "              bis dahin werden Verzeichnisaufträge abgelehnt\n"
        )
        problems += 1
    for dn, reason in remote.refused_ous:
        sys.stdout.write(f"              VERWORFEN ({reason}): {dn}\n")
        problems += 1
    dcs = ", ".join(remote.ad.dcs) or f"{remote_cfg.local_dc_fqdn()} (dieser DC)"
    sys.stdout.write(f"DC:           {dcs}\n")
    if not remote.ad.users_search_base:
        sys.stdout.write("Suchbasis:    keine — im Cockpit unter den AD-Einstellungen setzen\n")
        problems += 1
    return problems


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
        "AD-Zugang unvollständig: kein Domänencontroller bekannt. Im Cockpit die DCs "
        "eintragen oder den Agenten auf dem DC selbst betreiben."
    ),
    "ad_unreachable": (
        "Kein Domänencontroller auf Port 636 erreichbar. Hat der DC ein Zertifikat für "
        "LDAPS, und stimmen die Namen im Cockpit?"
    ),
    "ad_tls": (
        "LDAPS zum Domänencontroller gescheitert. Hat der DC ein Zertifikat für LDAPS, "
        "und vertraut dieser Server der ausstellenden CA?"
    ),
    "ad_timeout": "Der Domänencontroller antwortet nicht rechtzeitig.",
    "ad_auth": (
        "Die Kerberos-Anmeldung als Maschinenkonto wurde abgewiesen. Läuft der Befehl "
        "als Administrator (bzw. der Dienst als LocalSystem), und ist der DC-Name im "
        "Cockpit der volle DNS-Name (keine IP)?"
    ),
}


def _report_ad(remote: remote_cfg.RemoteConfig) -> int:
    """Bindet sich einmal ans AD, wie der Dienst es tut. Rückgabe: Anzahl Probleme.

    Von Hand aufgerufen läuft das als angemeldeter Administrator und nicht als
    LocalSystem — Kerberos nimmt dann dessen Ticket. Sagt also, ob LDAPS und
    Kerberos zum DC stehen; ob das Maschinenkonto die delegierten Rechte hat,
    zeigt erst ein Auftrag.
    """
    ad = build_ad_client(remote)
    if ad is None:
        sys.stdout.write("AD:           FEHLER — AD-Schicht nicht ladbar (siehe oben)\n")
        return 1
    probe = getattr(ad, "probe_service_connection_detailed", None)
    if probe is None:  # pragma: no cover — ältere AD-Schicht im Paket
        sys.stdout.write("AD:           nicht geprüft — die AD-Schicht kennt den Test nicht\n")
        return 0
    ok, reason = asyncio.run(probe())
    if ok:
        sys.stdout.write("AD:           ok — LDAPS mit Kerberos-Anmeldung gelungen\n")
        return 0
    text = AD_REASONS.get(reason, f"Bind gescheitert ({reason}).")
    sys.stdout.write(f"AD:           FEHLER — {text}\n")
    return 1


def build_ad_client(remote: remote_cfg.RemoteConfig) -> object | None:
    """AD-Client aus ``magister_api.ad`` bauen, mit den Werten aus dem Cockpit.

    Bewusst derselbe Code wie im direkten Pfad: siebzehn LDAP-Operationen ein
    zweites Mal zu schreiben hiesse, zwei Stände zu pflegen, von denen einer
    schlechter getestet ist. Angemeldet wird per Kerberos (SASL/GSSAPI über
    LDAPS) mit dem Konto, unter dem der Prozess läuft — als Dienst das
    Maschinenkonto des DC. Kein Passwort, nirgends.
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
        settings = Settings(**remote_cfg.ad_settings_kwargs(remote))  # type: ignore[arg-type]
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        sys.stderr.write(f"AD-Konfiguration ungültig in: {', '.join(fields)}\n")
        return None
    except Exception as exc:  # pragma: no cover — alles andere, ohne den Text
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
            "ausführen“.\n"
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

    enroll_cmd = sub.add_parser(
        "enroll", help="Endpunkt festhalten, Einmal-Token einlösen, Dienst starten"
    )
    enroll_cmd.add_argument(
        "--endpoint",
        default="",
        help="Connector-Endpunkt aus der Konsole, z. B. https://connect.magister.ch:46200. "
        "Legt die lokale Konfiguration an.",
    )
    enroll_cmd.add_argument(
        "--ca",
        default="",
        help="CA-Zertifikat der Plattform (PEM), falls sie eine eigene CA hat",
    )
    enroll_cmd.add_argument(
        "--ohne-start", action="store_true", help="den Dienst danach nicht starten"
    )
    enroll_cmd.add_argument(
        "--token",
        default="",
        help="Einmal-Token. Ohne diese Option wird es von stdin gelesen, "
        "damit es nicht in der Prozessliste steht.",
    )
    enroll_cmd.set_defaults(func=cmd_enroll)

    run_cmd = sub.add_parser("run", help="Abrufbetrieb (der Dienst)")
    run_cmd.set_defaults(func=cmd_run)

    check_cmd = sub.add_parser("check", help="Kanal, Konfiguration aus dem Cockpit und AD prüfen")
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
