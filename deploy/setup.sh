#!/usr/bin/env bash
# =============================================================================
#  JARVIS sunucu kurulumu - Ubuntu 24.04 (root/sudo ile calistirin)
#
#     sudo bash /opt/jarvis/jarvis-brain/deploy/setup.sh
#
#  Yaptiklari (tekrar calistirmak GUVENLIDIR - var olani bozmaz):
#   1. apt: python3-venv, git, ufw, curl
#   2. 'jarvis' sistem kullanicisi (root DEGIL, oturum acamaz)
#   3. /opt/jarvis/venv + requirements-server.txt
#   4. .env (yoksa .env.server.example'dan; JARVIS_TOKEN otomatik uretilir, chmod 600)
#   5. JARVIS_SERVER_BIND = Tailscale IP'si (Tailscale kuruluysa)
#   6. ufw: varsayilan GELEN = RED; yalnizca SSH + tailscale0 arayuzu serbest
#   7. systemd servisi (jarvis.service) - GEMINI_API_KEY doluysa baslatir
# =============================================================================
set -euo pipefail

APP_ROOT="/opt/jarvis"
APP_DIR="${APP_ROOT}/jarvis-brain"
VENV="${APP_ROOT}/venv"
VAULT="${APP_ROOT}/hafiza"
SVC_USER="jarvis"
ENV_FILE="${APP_DIR}/.env"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[HATA] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "root olarak calistirin: sudo bash $0"
[[ -f "${APP_DIR}/server/__main__.py" ]] || die "Kod ${APP_DIR} altinda bulunamadi (deploy/README.md adim 5)."

# ----------------------------------------------------------------- 1. paketler
say "Sistem paketleri"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ufw curl ca-certificates >/dev/null
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python ${PYV} cok eski; 3.11+ gerekli (Ubuntu 24.04'te 3.12 gelir)."
echo "Python ${PYV}"

# ----------------------------------------------------------------- 2. kullanici
say "Servis kullanicisi: ${SVC_USER}"
if ! id -u "${SVC_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_ROOT}" --shell /usr/sbin/nologin "${SVC_USER}"
  echo "olusturuldu"
else
  echo "zaten var"
fi
mkdir -p "${VAULT}" "${APP_DIR}/data/logs" "${APP_DIR}/bridge"

# ----------------------------------------------------------------- 3. venv
say "Python sanal ortami + bagimliliklar (${VENV})"
[[ -x "${VENV}/bin/python" ]] || python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -q --upgrade pip
"${VENV}/bin/pip" install -q -r "${APP_DIR}/requirements-server.txt"

# ----------------------------------------------------------------- 4. .env
say ".env"
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/.env.server.example" "${ENV_FILE}"
  echo "${ENV_FILE} ornekten olusturuldu"
fi
if ! grep -qE '^JARVIS_TOKEN=.{24,}' "${ENV_FILE}"; then
  TOKEN=$("${VENV}/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')
  if grep -qE '^JARVIS_TOKEN=' "${ENV_FILE}"; then
    sed -i "s|^JARVIS_TOKEN=.*|JARVIS_TOKEN=${TOKEN}|" "${ENV_FILE}"
  else
    echo "JARVIS_TOKEN=${TOKEN}" >> "${ENV_FILE}"
  fi
  echo "JARVIS_TOKEN uretildi -> PC'deki client/.env'e AYNISINI yazin:"
  echo "   sudo grep ^JARVIS_TOKEN= ${ENV_FILE}"
fi

# ----------------------------------------------------------------- 5. Tailscale bind
say "Tailscale"
if command -v tailscale >/dev/null 2>&1 && TS_IP=$(tailscale ip -4 2>/dev/null | head -n1) && [[ -n "${TS_IP}" ]]; then
  sed -i "s|^JARVIS_SERVER_BIND=.*|JARVIS_SERVER_BIND=${TS_IP}|" "${ENV_FILE}"
  grep -qE '^JARVIS_SERVER_BIND=' "${ENV_FILE}" || echo "JARVIS_SERVER_BIND=${TS_IP}" >> "${ENV_FILE}"
  echo "Sunucu Tailscale IP'sine baglanacak: ${TS_IP}"
else
  warn "Tailscale kurulu/bagli degil -> sunucu yalnizca 127.0.0.1'de dinler (PC'den erisilemez)."
  warn "Kurmak icin: curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
  warn "Sonra bu betigi tekrar calistirin."
fi

# ----------------------------------------------------------------- izinler
chown -R "${SVC_USER}:${SVC_USER}" "${APP_ROOT}"
chmod 600 "${ENV_FILE}"
chmod 700 "${APP_DIR}/data"

# ----------------------------------------------------------------- 6. ufw
say "Guvenlik duvari (ufw)"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# ONCE SSH (acik oturumu kilitlememek icin), sonra Tailscale arayuzu
ufw allow OpenSSH >/dev/null
if ip link show tailscale0 >/dev/null 2>&1; then
  ufw allow in on tailscale0 >/dev/null
  echo "tailscale0 arayuzune izin verildi"
else
  warn "tailscale0 arayuzu yok - Tailscale kurduktan sonra betigi tekrar calistirin."
fi
ufw --force enable >/dev/null
ufw status verbose | sed -n '1,20p'

# ----------------------------------------------------------------- 7. systemd
say "systemd servisi"
install -m 644 "${APP_DIR}/deploy/jarvis.service" /etc/systemd/system/jarvis.service
systemctl daemon-reload
systemctl enable jarvis >/dev/null
if grep -qE '^GEMINI_API_KEY=.+' "${ENV_FILE}"; then
  systemctl restart jarvis
  sleep 3
  systemctl --no-pager --lines=15 status jarvis || true
else
  warn "GEMINI_API_KEY bos - servis ETKIN ama BASLATILMADI."
  warn "Doldurun:  sudo nano ${ENV_FILE}   sonra:  sudo systemctl start jarvis"
fi

say "Bitti. Loglari izleyin:  journalctl -u jarvis -f"
