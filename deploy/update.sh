#!/usr/bin/env bash
#
# Bringt die laufende Installation auf den neuesten Stand des Branches:
# Quellcode holen, Abhängigkeiten angleichen, Dienst neu starten.
#
# Aufruf als root:  bash /opt/aktien-kurse/deploy/update.sh
# Optional:         BRANCH=main  (Standard: der aktuell ausgecheckte Branch)
#
set -euo pipefail

APP_DIR="/opt/aktien-kurse"
APP_USER="aktien"

info() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen." >&2; exit 1; }
[[ -d "$APP_DIR/.git" ]] || { echo "$APP_DIR ist keine Git-Arbeitskopie — erst setup-server.sh ausführen." >&2; exit 1; }

BRANCH="${BRANCH:-$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)}"

info "Datenbank sichern"
# .backup ist auch bei laufendem Dienst konsistent (anders als ein cp)
if [[ -f "$APP_DIR/kurse.db" ]]; then
    SICHERUNG="$APP_DIR/kurse.db.$(date +%Y%m%d-%H%M%S).bak"
    sqlite3 "$APP_DIR/kurse.db" ".backup '$SICHERUNG'"
    chown "$APP_USER:$APP_USER" "$SICHERUNG"
    echo "    $SICHERUNG"
fi

info "Quellcode aktualisieren ($BRANCH)"
git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
git -C "$APP_DIR" checkout --quiet "$BRANCH"
git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"

info "Abhängigkeiten angleichen"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# Falls sich die Unit-Datei im Repo geändert hat
if ! cmp -s "$APP_DIR/deploy/aktien-kurse.service" /etc/systemd/system/aktien-kurse.service; then
    info "systemd-Dienstdatei hat sich geändert — wird übernommen"
    install -m 644 "$APP_DIR/deploy/aktien-kurse.service" /etc/systemd/system/aktien-kurse.service
    systemctl daemon-reload
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

info "Dienst neu starten"
systemctl restart aktien-kurse
sleep 2
if systemctl is-active --quiet aktien-kurse; then
    echo "    läuft — https-Aufruf sollte wieder funktionieren."
else
    echo "    Dienst läuft NICHT. Ursache: journalctl -u aktien-kurse -n 50 --no-pager" >&2
    exit 1
fi
