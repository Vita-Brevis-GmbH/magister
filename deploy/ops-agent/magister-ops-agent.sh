#!/usr/bin/env bash
#
# Magister ops-agent — the privileged host side of the WebUI System controls.
#
# The (unprivileged) API container drops request files into $OPS_DIR/requests/.
# This script — run by a systemd timer as a host user that may drive Docker —
# executes each request (container restart, or git-pull + rebuild + up) and
# writes the outcome to $OPS_DIR/status.json for the WebUI to display.
#
# It intentionally understands ONLY two fixed actions ("restart"/"update").
# It never evals anything from the request file beyond that whitelist, so a
# compromised WebUI cannot turn this into arbitrary host command execution.
#
# Config via environment (see magister-ops-agent.service):
#   OPS_DIR       shared dir with the API        (default /opt/magister/ops)
#   REPO_DIR      git checkout to pull/build      (default /opt/magister/magister)
#   COMPOSE_FILE  compose file to drive           (default $REPO_DIR/deploy/compose/docker-compose.yml)
#   COMPOSE_ENV   optional --env-file             (default $REPO_DIR/deploy/compose/.env)

set -uo pipefail

OPS_DIR="${OPS_DIR:-/opt/magister/ops}"
REPO_DIR="${REPO_DIR:-/opt/magister/magister}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_DIR/deploy/compose/docker-compose.yml}"
COMPOSE_ENV="${COMPOSE_ENV:-$REPO_DIR/deploy/compose/.env}"

REQ_DIR="$OPS_DIR/requests"
STATUS="$OPS_DIR/status.json"
LOGFILE="$OPS_DIR/last.log"

compose() {
  if [ -f "$COMPOSE_ENV" ]; then
    docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" "$@"
  else
    docker compose -f "$COMPOSE_FILE" "$@"
  fi
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

git_sha() { git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown"; }

# json-escape a string for embedding in status.json (backslash, quote, newlines).
json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"}{print}'
}

write_status() {
  # $1=action $2=state $3=message $4=started $5=finished
  local tmp="$STATUS.tmp"
  {
    printf '{"action":"%s","state":"%s","message":"%s","git_sha":"%s","started_at":"%s","finished_at":"%s"}\n' \
      "$1" "$2" "$(json_escape "$3")" "$(git_sha)" "$4" "$5"
  } >"$tmp"
  mv -f "$tmp" "$STATUS"
}

# Run an action, streaming its combined output live to $LOGFILE (so the WebUI
# can show progress while it runs). Returns the action's real exit code, not
# tee's, via pipefail.
run_action() {
  local action="$1"
  set -o pipefail
  case "$action" in
    restart)
      compose restart 2>&1 | tee -a "$LOGFILE"
      ;;
    update)
      {
        git -C "$REPO_DIR" pull --ff-only 2>&1 && \
          compose build 2>&1 && \
          compose up -d 2>&1
      } | tee -a "$LOGFILE"
      ;;
    *)
      echo "unknown action: $action" | tee -a "$LOGFILE"
      return 2
      ;;
  esac
}

[ -d "$REQ_DIR" ] || exit 0

# Process pending requests oldest-first, one at a time.
for req in $(ls -1tr "$REQ_DIR"/*.json 2>/dev/null); do
  action="$(sed -n 's/.*"action"[[:space:]]*:[[:space:]]*"\([a-zA-Z_]*\)".*/\1/p' "$req")"
  started="$(now)"
  case "$action" in
    restart|update) : ;;
    *)
      write_status "${action:-invalid}" "error" "unknown or unparseable action" "$started" "$(now)"
      rm -f "$req"
      continue
      ;;
  esac

  # Fresh log for this run; the WebUI polls it live via the status endpoint.
  : >"$LOGFILE"
  write_status "$action" "running" "" "$started" ""
  run_action "$action"
  code=$?
  # status.json keeps only the tail; last.log has the full output.
  tail_out="$(tail -c 2000 "$LOGFILE" 2>/dev/null)"
  if [ "$code" -eq 0 ]; then
    write_status "$action" "success" "$tail_out" "$started" "$(now)"
  else
    write_status "$action" "error" "$tail_out" "$started" "$(now)"
  fi
  rm -f "$req"
done
