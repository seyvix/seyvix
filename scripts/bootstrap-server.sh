#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu/Debian server. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/scripts/bootstrap-server.sh | bash -s -- deploy
#   (or copy the file and run: bash bootstrap-server.sh [deploy-user] [deploy-dir])
#
# Installs Docker Engine + compose plugin, adds 2 GB swap (if none), opens only SSH/80/443
# in ufw, creates the deploy user (docker group, SSH login with keys only) and deploy dir.
set -euo pipefail

user=${1:-deploy}
dir=${2:-/opt/seyvix}
[[ $(id -u) -eq 0 ]] || { echo "run as root" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl ufw openssl

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if [[ -z $(swapon --show --noheadings) ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
echo 'vm.swappiness=10' >/etc/sysctl.d/90-seyvix.conf
sysctl --quiet --system

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

if ! id "$user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$user"
fi
usermod -aG docker "$user"
install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
if [[ -f /root/.ssh/authorized_keys && ! -f /home/$user/.ssh/authorized_keys ]]; then
  install -m 600 -o "$user" -g "$user" /root/.ssh/authorized_keys "/home/$user/.ssh/authorized_keys"
fi
install -d -m 750 -o "$user" -g "$user" "$dir"

echo
echo "Done. Next (as $user, in $dir): put docker-compose.yml + scripts/ there,"
echo "run scripts/init-env.sh and edit .env, then deploy (see README)."
echo "Docker: $(docker --version); compose: $(docker compose version --short)"
