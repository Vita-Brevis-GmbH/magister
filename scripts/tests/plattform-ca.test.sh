#!/usr/bin/env bash
# Die Test-CA aus plattform-aufbau.sh (`make_ca`) hält RFC 5280 ein — ohne
# sich auf die Vorgaben einer OpenSSL-Fassung zu verlassen.
#
# Warum es diesen Test gibt: ab Python 3.13 prüft der Connector-Agent mit
# VERIFY_X509_STRICT, und OpenSSL lehnt dann jede Kette ab, in der einem
# Zertifikat der Authority Key Identifier fehlt ("Missing Authority Key
# Identifier"). OpenSSL 3 setzt SKI und AKI von selbst, 1.1.1 nicht — auf
# einem Rechner mit OpenSSL 3 sähe man ein Skript, das sich darauf verlässt,
# also nie. Deshalb läuft `make_ca` hier mit einem `openssl`, das wie 1.1.1
# nur die Kennungen setzt, die ausdrücklich verlangt sind. Geprüft wird mit
# `openssl verify -x509_strict`, derselben Prüfung, die Python 3.13 einschaltet.
#
# Braucht weder Docker noch Netz, nur openssl.
#
#   ./scripts/tests/plattform-ca.test.sh

set -uo pipefail

SKRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/plattform-aufbau.sh"
ARBEIT="$(mktemp -d)"
trap 'rm -rf "$ARBEIT"' EXIT

GRUEN=0
ROT=0

pruefe() {  # $1 = Beschreibung, $2 = erwartet, $3 = tatsächlich
  if [ "$2" = "$3" ]; then
    printf '\033[32m  ok  \033[0m%s\n' "$1"
    GRUEN=$((GRUEN + 1))
  else
    printf '\033[31m  !!  %s\033[0m\n      erwartet: %s\n      erhalten: %s\n' "$1" "$2" "$3"
    ROT=$((ROT + 1))
  fi
}

# `openssl` wie OpenSSL 1.1.1: keine Schlüsselkennung, die nicht ausdrücklich
# verlangt ist. OpenSSL 3 fügt sie sonst beim Ausstellen von selbst hinzu.
cat > "$ARBEIT/ohne-vorgaben.sh" <<'EOF'
openssl() {
  local args=("$@") i ext extfile=""
  case "$1" in
    req)
      case " $* " in *" -x509 "*) ;; *) command openssl "$@"; return ;; esac
      case "$*" in *subjectKeyIdentifier*) ;; *) args+=(-addext subjectKeyIdentifier=none) ;; esac
      case "$*" in *authorityKeyIdentifier*) ;; *) args+=(-addext authorityKeyIdentifier=none) ;; esac
      ;;
    x509)
      case " $* " in *" -req "*) ;; *) command openssl "$@"; return ;; esac
      ext="$(mktemp "$ARBEIT/ext.XXXXXX")"
      for ((i = 0; i < ${#args[@]}; i++)); do
        if [ "${args[i]}" = -extfile ]; then
          cat "${args[i + 1]}" > "$ext"
          args[i + 1]="$ext"
          extfile=ja
        fi
      done
      [ -n "$extfile" ] || args+=(-extfile "$ext")
      grep -q '^subjectKeyIdentifier' "$ext" || echo 'subjectKeyIdentifier=none' >> "$ext"
      grep -q '^authorityKeyIdentifier' "$ext" || echo 'authorityKeyIdentifier=none' >> "$ext"
      ;;
  esac
  command openssl "${args[@]}"
}
EOF

sed -n '/^make_ca()/,/^}/p; /^konsolen_san()/,/^}/p; /^konsolen_zertifikat()/,/^}/p;
        /^zertifikat_deckt_ab()/,/^}/p; /^zertifikat()/,/^}/p' "$SKRIPT" > "$ARBEIT/ca.sh"

CERTS="$ARBEIT/certs"
(
  export ARBEIT
  say() { :; }
  warn() { :; }
  die() { echo "DIE: $*" >&2; exit 1; }
  CERTS="$CERTS" DOMAIN=mgmt.example.ch KONSOLE_HOST=console.mgmt.example.ch BIND=127.0.0.1
  ZUSATZNAME="" KONSOLE_PFAD="$ARBEIT/konsole" ART=test
  # shellcheck source=/dev/null
  source "$ARBEIT/ohne-vorgaben.sh"
  # shellcheck source=/dev/null
  source "$ARBEIT/ca.sh"
  make_ca
)

ski() { command openssl x509 -in "$1" -noout -ext subjectKeyIdentifier 2>/dev/null | sed -n 2p | tr -d ' '; }
aki() {
  command openssl x509 -in "$1" -noout -ext authorityKeyIdentifier 2>/dev/null \
    | sed -n 2p | sed 's/keyid://' | tr -d ' '
}
traegt_aki_von() {  # $1 = Zertifikat, $2 = Aussteller
  local a s
  a="$(aki "$CERTS/$1.pem")"
  s="$(ski "$CERTS/$2.pem")"
  if [ -n "$a" ] && [ "$a" = "$s" ]; then echo ja; else echo "nein (AKI '$a', SKI '$s')"; fi
}
strikt() {  # $1 = Zertifikat, Rest = weitere Argumente für openssl verify
  local blatt="$1"; shift
  command openssl verify -x509_strict -CAfile "$CERTS/root.pem" "$@" "$CERTS/$blatt.pem" 2>&1 | tail -1
}

printf '\n\033[1m1 · make_ca stellt alles aus — auch ohne die Vorgaben von OpenSSL 3\033[0m\n'
for datei in root operator-int connector-int console tenants connector operator monitor; do
  pruefe "$datei.pem vorhanden" "ja" "$([ -s "$CERTS/$datei.pem" ] && echo ja || echo nein)"
done

printf '\n\033[1m2 · Schlüsselkennungen verbinden jedes Zertifikat mit seinem Aussteller\033[0m\n'
pruefe "Wurzel trägt einen Subject Key Identifier" "ja" \
  "$([ -n "$(ski "$CERTS/root.pem")" ] && echo ja || echo nein)"
for datei in operator-int connector-int console tenants connector; do
  pruefe "$datei: AKI = SKI der Wurzel" "ja" "$(traegt_aki_von "$datei" root)"
done
for datei in operator monitor; do
  pruefe "$datei: AKI = SKI des Operator-Zweigs" "ja" "$(traegt_aki_von "$datei" operator-int)"
done

printf '\n\033[1m3 · Strikte Prüfung nach RFC 5280, wie Python 3.13 sie einschaltet\033[0m\n'
pruefe "connector.pem (Listener 46200, den der Agent prüft)" "$CERTS/connector.pem: OK" \
  "$(strikt connector)"
pruefe "console.pem" "$CERTS/console.pem: OK" "$(strikt console)"
pruefe "tenants.pem" "$CERTS/tenants.pem: OK" "$(strikt tenants)"
pruefe "operator.pem über den Operator-Zweig" "$CERTS/operator.pem: OK" \
  "$(strikt operator -untrusted "$CERTS/operator-int.pem")"
pruefe "connector-int.pem" "$CERTS/connector-int.pem: OK" "$(strikt connector-int)"

printf '\n\033[1m4 · Gegenprobe: ohne ausdrückliche Kennungen fällt die Prüfung durch\033[0m\n'
# Sonst bewiese Abschnitt 3 nichts: setzte das nachgebildete openssl die
# Kennungen doch, bestünde jedes Skript.
GEGEN="$(
  export ARBEIT
  # shellcheck source=/dev/null
  source "$ARBEIT/ohne-vorgaben.sh"
  cd "$ARBEIT" || exit 1
  openssl req -newkey rsa:2048 -nodes -keyout gegen-key.pem -out gegen.csr -subj "/CN=gegen" 2>/dev/null
  openssl x509 -req -in gegen.csr -CA "$CERTS/root.pem" -CAkey "$CERTS/root-key.pem" \
    -CAcreateserial -days 1 -sha256 -out gegen.pem \
    -extfile <(printf 'extendedKeyUsage=serverAuth\n') 2>/dev/null
  command openssl verify -x509_strict -CAfile "$CERTS/root.pem" gegen.pem 2>&1
)"
pruefe "Blatt ohne AKI wird abgelehnt" "ja" \
  "$(printf '%s' "$GEGEN" | grep -q 'Missing Authority Key Identifier' && echo ja || echo "nein: $GEGEN")"

printf '\n'
if [ "$ROT" -eq 0 ]; then
  printf '\033[32m%d bestanden, 0 gescheitert\033[0m\n' "$GRUEN"
  exit 0
fi
printf '\033[31m%d bestanden, %d gescheitert\033[0m\n' "$GRUEN" "$ROT"
exit 1
