#!/usr/bin/env bash
#
# Richtet die Kurs-Anwendung auf einem frischen Ubuntu-24.04-Server ein
# (Hetzner Cloud). Das Skript ist wiederholbar: ein zweiter Aufruf aktualisiert
# nur, was sich geändert hat.
#
# Aufruf als root:
#
#   DOMAIN=kurse.example.de EMAIL=du@example.de bash deploy/setup-server.sh
#
# Optionale Variablen:
#   BASIC_AUTH_USER  Benutzername für den Passwortschutz (Standard: kurse)
#   REPO_URL         Git-Repository (Standard: dieses Projekt auf GitHub)
#   BRANCH           Zu deployender Branch (Standard: main)
#   SKIP_TLS=1       Certbot überspringen (z. B. wenn die DNS-Einträge noch
#                    nicht gesetzt sind — später nachholbar, siehe DEPLOY.md)
#
set -euo pipefail

APP_DIR="/opt/aktien-kurse"
APP_USER="aktien"
REPO_URL="${REPO_URL:-https://github.com/thd95/hello-world-py.git}"
BRANCH="${BRANCH:-main}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-kurse}"
HTPASSWD_DATEI="/etc/nginx/aktien-kurse.htpasswd"
SKRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fehler() { printf '\n\033[1;31mFehler: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fehler "Bitte als root ausführen (sudo bash deploy/setup-server.sh)."
[[ -n "${DOMAIN:-}" ]] || fehler "DOMAIN ist nicht gesetzt, z. B. DOMAIN=kurse.example.de"
if [[ -z "${SKIP_TLS:-}" && -z "${EMAIL:-}" ]]; then
    fehler "EMAIL ist nicht gesetzt (für Let's-Encrypt-Ablaufwarnungen). Alternativ SKIP_TLS=1 setzen."
fi

# ── 1. Pakete ──────────────────────────────────────────────────────────────
info "Pakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    git python3 python3-venv python3-pip \
    nginx apache2-utils certbot python3-certbot-nginx \
    sqlite3 ufw unattended-upgrades

# Sicherheitsupdates automatisch einspielen
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

# ── 2. Dienstbenutzer ──────────────────────────────────────────────────────
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    info "Benutzer $APP_USER anlegen"
    adduser --system --group --no-create-home --home "$APP_DIR" "$APP_USER"
else
    info "Benutzer $APP_USER existiert bereits"
fi

# ── 3. Quellcode ───────────────────────────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
    info "Repository aktualisieren ($BRANCH)"
    git -C "$APP_DIR" remote set-url origin "$REPO_URL"
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" checkout --quiet "$BRANCH"
    git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
    info "Repository nach $APP_DIR klonen"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

# ── 4. Virtuelle Umgebung ──────────────────────────────────────────────────
info "Python-Abhängigkeiten installieren"
[[ -x "$APP_DIR/.venv/bin/python" ]] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# kurse.db und der Arbeitsordner gehören dem Dienstbenutzer
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 5. systemd-Dienst ──────────────────────────────────────────────────────
info "systemd-Dienst einrichten"
install -m 644 "$APP_DIR/deploy/aktien-kurse.service" /etc/systemd/system/aktien-kurse.service
systemctl daemon-reload
systemctl enable --quiet aktien-kurse
systemctl restart aktien-kurse

sleep 2
systemctl is-active --quiet aktien-kurse \
    || fehler "Dienst startet nicht — Ursache anzeigen mit: journalctl -u aktien-kurse -n 50 --no-pager"

# ── 6. Passwortschutz ──────────────────────────────────────────────────────
if [[ -f "$HTPASSWD_DATEI" ]]; then
    info "Passwortdatei existiert bereits ($HTPASSWD_DATEI) — unverändert"
else
    info "Passwort für den Benutzer „$BASIC_AUTH_USER“ festlegen"
    htpasswd -c "$HTPASSWD_DATEI" "$BASIC_AUTH_USER"
    chown root:www-data "$HTPASSWD_DATEI"
    chmod 640 "$HTPASSWD_DATEI"
fi

# ── 7. nginx ───────────────────────────────────────────────────────────────
info "nginx konfigurieren für $DOMAIN"
if [[ -f /etc/nginx/sites-enabled/aktien-kurse.conf ]] \
   && grep -q "server_name .*$DOMAIN" /etc/nginx/sites-available/aktien-kurse.conf 2>/dev/null; then
    # Vorhandene Konfiguration nicht überschreiben — certbot hat dort
    # womöglich schon den HTTPS-Block eingetragen.
    echo "    Bestehende Konfiguration für $DOMAIN gefunden — bleibt erhalten."
else
    sed "s/__DOMAIN__/$DOMAIN/g" "$SKRIPT_DIR/nginx-aktien-kurse.conf" \
        > /etc/nginx/sites-available/aktien-kurse.conf
    ln -sf /etc/nginx/sites-available/aktien-kurse.conf /etc/nginx/sites-enabled/aktien-kurse.conf
fi
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ── 8. Firewall ────────────────────────────────────────────────────────────
info "Firewall (ufw) einrichten"
ufw allow OpenSSH >/dev/null      # zuerst SSH, sonst sperrt man sich aus
ufw allow 'Nginx Full' >/dev/null # 80 und 443
ufw --force enable >/dev/null
ufw status verbose | sed 's/^/    /'

# ── 9. TLS-Zertifikat ──────────────────────────────────────────────────────
if [[ -n "${SKIP_TLS:-}" ]]; then
    info "TLS übersprungen (SKIP_TLS gesetzt)"
    echo "    Später nachholen mit:"
    echo "      certbot --nginx -d $DOMAIN --agree-tos -m DEINE@MAIL --redirect"
else
    info "Let's-Encrypt-Zertifikat anfordern"
    certbot --nginx -d "$DOMAIN" --agree-tos -m "$EMAIL" --redirect --non-interactive \
        || fehler "Certbot fehlgeschlagen. Zeigt der A-Record von $DOMAIN wirklich auf diesen Server? Prüfen mit: dig +short $DOMAIN"
    systemctl reload nginx
fi

# ── Fertig ─────────────────────────────────────────────────────────────────
info "Fertig"
cat <<ENDE
    Anwendung:   https://$DOMAIN   (Benutzer: $BASIC_AUTH_USER)
    Status:      systemctl status aktien-kurse
    Protokoll:   journalctl -u aktien-kurse -f
    Aktualisieren: bash $APP_DIR/deploy/update.sh
ENDE
