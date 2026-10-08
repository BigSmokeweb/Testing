#!/usr/bin/env bash
# AutoQA VPS Setup Script
# Run as root on a fresh Ubuntu 22.04/24.04 VPS:
#   curl -fsSL https://raw.githubusercontent.com/yourorg/autoqa/main/scripts/setup_vps.sh | bash
#
# Or copy-paste manually. Safe to re-run (idempotent).
set -euo pipefail

DEPLOY_USER="autoqa"
APP_DIR="/home/${DEPLOY_USER}/autoqa"

echo "=== [1/9] System update ==="
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y --no-install-recommends \
    curl git ufw unattended-upgrades apt-transport-https \
    ca-certificates gnupg lsb-release iptables-persistent

echo "=== [2/9] Create deploy user: ${DEPLOY_USER} ==="
if ! id "${DEPLOY_USER}" &>/dev/null; then
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
    usermod -aG sudo "${DEPLOY_USER}"
    echo "  Created user ${DEPLOY_USER}"
fi

# Copy root's authorized_keys (assumes you logged in as root with your SSH key)
mkdir -p "/home/${DEPLOY_USER}/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
    chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
    chmod 700 "/home/${DEPLOY_USER}/.ssh"
    chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"
    echo "  Copied SSH authorized_keys to ${DEPLOY_USER}"
fi

echo "=== [3/9] Harden SSH ==="
# Disable password auth, root login
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd
echo "  SSH hardened (keys only, no root login)"

echo "=== [4/9] Firewall (ufw) ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 QUIC'
ufw --force enable
echo "  ufw enabled: 22, 80, 443"

echo "=== [5/9] Unattended security upgrades ==="
dpkg-reconfigure -plow unattended-upgrades
echo "  Unattended upgrades configured"

echo "=== [6/9] Install Docker ==="
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" \
      | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    echo "  Docker installed"
else
    echo "  Docker already installed: $(docker --version)"
fi

# Allow deploy user to use docker
usermod -aG docker "${DEPLOY_USER}"

echo "=== [7/9] Clone project ==="
if [ ! -d "${APP_DIR}" ]; then
    sudo -u "${DEPLOY_USER}" git clone https://github.com/yourorg/autoqa.git "${APP_DIR}"
    echo "  Cloned to ${APP_DIR}"
else
    echo "  ${APP_DIR} already exists — skipping clone (run git pull manually)"
fi

echo "=== [8/9] Create .env from .env.example ==="
if [ ! -f "${APP_DIR}/.env" ]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    # Generate random keys
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    PG_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s|CHANGEME_run_python_secrets_token_urlsafe_48|${SECRET_KEY}|g"  "${APP_DIR}/.env"
    sed -i "s|CHANGEME_run_Fernet_generate_key|${FERNET_KEY}|g"              "${APP_DIR}/.env"
    sed -i "s|POSTGRES_PASSWORD=CHANGEME|POSTGRES_PASSWORD=${PG_PASS}|g"    "${APP_DIR}/.env"
    sed -i "s|DATABASE_URL=postgresql://autoqa:CHANGEME|DATABASE_URL=postgresql://autoqa:${PG_PASS}|g" "${APP_DIR}/.env"
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    echo "  .env created with generated keys"
    echo ""
    echo "  *** ACTION REQUIRED ***"
    echo "  Edit ${APP_DIR}/.env and set DOMAIN=yourdomain.com"
    echo "  Then re-run: cd ${APP_DIR} && docker compose up -d --build"
else
    echo "  .env already exists — skipping"
fi

echo "=== [9/9] Logrotate for security.log ==="
cat > /etc/logrotate.d/autoqa <<'EOF'
/home/autoqa/autoqa/security.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 0640 autoqa autoqa
}
EOF

echo ""
echo "========================================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. SSH back in as ${DEPLOY_USER} (not root)"
echo "  2. Edit ${APP_DIR}/.env — set DOMAIN=yourdomain.com"
echo "  3. cd ${APP_DIR} && docker compose up -d --build"
echo "  4. docker compose exec web alembic upgrade head"
echo "  5. Apply iptables rules (see README.md Step 5)"
echo "  6. Visit https://yourdomain.com"
echo "========================================================"
