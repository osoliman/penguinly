#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Penguinly — AWS Lightsail deployment script
# Tested on Ubuntu 22.04 LTS (Lightsail $5/mo instance or higher)
#
# Usage:
#   1. SSH into your Lightsail instance
#   2. Upload this repo to /home/ubuntu/penguinly  (scp / git clone)
#   3. chmod +x deploy.sh && sudo ./deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/home/ubuntu/penguinly"
SERVICE_NAME="penguinly"
NGINX_CONF="/etc/nginx/sites-available/penguinly"

echo "==> Updating system packages"
apt-get update -y
apt-get upgrade -y
apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

echo "==> Creating log directory"
mkdir -p /var/log/penguinly
chown ubuntu:ubuntu /var/log/penguinly

echo "==> Setting up Python virtual environment"
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Copying .env (if not present)"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  # Generate a random secret key
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/your-very-long-random-secret-key-here/$SECRET/" "$APP_DIR/.env"
  echo "  → .env created. Edit $APP_DIR/.env to set DATABASE_URL if needed."
fi

echo "==> Initialising database"
cd "$APP_DIR"
FLASK_ENV=production ./venv/bin/flask --app app init-db

echo "==> Installing systemd service"
cp "$APP_DIR/penguinly.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "  → Service status:"
systemctl is-active "$SERVICE_NAME" && echo "  ✓ Running" || echo "  ✗ Failed — check: journalctl -u $SERVICE_NAME"

echo "==> Configuring nginx"
cp "$APP_DIR/nginx.conf" "$NGINX_CONF"
ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/penguinly"
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "  → nginx reloaded"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Penguinly is deployed!"
echo ""
echo "  Next steps:"
echo "  1. Open port 80 (and 443) in your Lightsail firewall"
echo "  2. Point your domain's A record to this instance's"
echo "     static IP address"
echo "  3. Run: sudo certbot --nginx -d yourdomain.com"
echo "     to enable HTTPS (free via Let's Encrypt)"
echo "  4. Seed demo data: flask --app app seed-db"
echo "══════════════════════════════════════════════════════"
