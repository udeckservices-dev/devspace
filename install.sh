#!/bin/bash
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  DevSpace â€” VPS Install Script
#  Run this ONCE on your fresh Linux VPS (Ubuntu/Debian/CentOS)
#
#  Usage:
#    chmod +x install.sh
#    sudo bash install.sh
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

set -e

APP_USER=$(logname 2>/dev/null || echo "$SUDO_USER" || echo "ubuntu")
APP_DIR="/opt/devspace"
REPOS_DIR="/opt/devspace/repos"
VENV_DIR="$APP_DIR/venv"
APP_PORT=5000

echo ""
echo "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
echo "â•‘     DevSpace â€” VPS Setup             â•‘"
echo "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"
echo ""
echo "â†’ App user  : $APP_USER"
echo "â†’ App dir   : $APP_DIR"
echo "â†’ Repos dir : $REPOS_DIR"
echo "â†’ Port      : $APP_PORT"
echo ""

# â”€â”€ 1. System packages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[1/7] Installing system packages..."
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq git python3 python3-pip python3-venv curl
elif command -v yum &>/dev/null; then
    yum install -y git python3 python3-pip curl
fi
echo "      âœ“ Done"

# â”€â”€ 2. Create app directory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[2/7] Creating directories..."
mkdir -p "$APP_DIR"
mkdir -p "$REPOS_DIR"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
echo "      âœ“ $APP_DIR and $REPOS_DIR created"

# â”€â”€ 3. Copy app files (run from the directory containing your app) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[3/7] Copying app files to $APP_DIR..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rsync -a --exclude='.git' --exclude='__pycache__' \
      --exclude='*.pyc' --exclude='.env' \
      --exclude='devspace.db' \
      "$SCRIPT_DIR/" "$APP_DIR/"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
echo "      âœ“ Files copied"

# â”€â”€ 4. Python virtualenv + dependencies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[4/7] Setting up Python virtualenv..."
sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"
# Install gunicorn for production serving
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -q gunicorn
echo "      âœ“ virtualenv ready"

# â”€â”€ 5. .env file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[5/7] Setting up .env file..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.live" "$APP_DIR/.env"
    # Generate random secrets
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    DSECRET=$(python3 -c "import secrets; print(secrets.token_hex(16))")
    # Detect public IP
    PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_VPS_IP")

    sed -i "s|CHANGE-THIS-to-a-long-random-string-min-32-chars|$SECRET|g" "$APP_DIR/.env"
    sed -i "s|CHANGE-THIS-to-another-long-random-string|$DSECRET|g" "$APP_DIR/.env"
    sed -i "s|YOUR_VPS_IP_OR_DOMAIN|$PUBLIC_IP|g" "$APP_DIR/.env"
    sed -i "s|YOUR_LINUX_USERNAME|$APP_USER|g" "$APP_DIR/.env"

    echo "      âœ“ .env created with auto-generated secrets"
    echo "      âœ— EDIT $APP_DIR/.env to set VPS_HOST and other settings!"
else
    echo "      âœ“ .env already exists, skipping"
fi

# â”€â”€ 6. Initialise database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[6/7] Initialising database..."
cd "$APP_DIR"
sudo -u "$APP_USER" "$VENV_DIR/bin/python" run.py &
RUN_PID=$!
sleep 3
kill $RUN_PID 2>/dev/null || true
echo "      âœ“ Database initialised"

# â”€â”€ 7. Systemd service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "[7/7] Creating systemd service..."
cat > /etc/systemd/system/devspace.service <<EOF
[Unit]
Description=DevSpace â€” Git Deploy Server
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn run:app \\
    --workers 2 \\
    --bind 0.0.0.0:$APP_PORT \\
    --timeout 120 \\
    --access-logfile $APP_DIR/access.log \\
    --error-logfile  $APP_DIR/error.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable devspace
systemctl start devspace

echo "      âœ“ Service started"

# â”€â”€ Done â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo "â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
echo "â•‘  âœ“  DevSpace installed successfully!                 â•‘"
echo "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"
echo ""
echo "  App running at : http://$(curl -s ifconfig.me 2>/dev/null):$APP_PORT"
echo "  Admin login    : admin@example.com / change-this-password"
echo "  Repos stored at: $REPOS_DIR"
echo ""
echo "  â–º IMPORTANT: Edit $APP_DIR/.env"
echo "    Set VPS_HOST=your-domain-or-ip"
echo "    Set SSH_USER=$APP_USER"
echo ""
echo "  â–º Check status : sudo systemctl status devspace"
echo "  â–º View logs    : sudo journalctl -u devspace -f"
echo ""
echo "  â–º Add SSH key for git push:"
echo "    On your Windows PC run:"
echo "    cat ~/.ssh/id_rsa.pub"
echo "    Then on VPS append to: ~/.ssh/authorized_keys"
echo ""
