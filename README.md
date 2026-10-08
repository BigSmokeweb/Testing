# AutoQA

Automated website quality & reliability testing — broken links, console errors, page load time, network failures, with optional test-account login (Mode A). Multi-user, SSRF-protected, Playwright-powered.

---

## Local Development

### Prerequisites
- Python 3.12+
- Redis (local or Docker: `docker run -p 6379:6379 redis`)
- (Optional) PostgreSQL — defaults to SQLite for local dev

### Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install chromium
alembic upgrade head           # apply migrations
```

### Run
```bash
# Terminal 1 — web server
uvicorn app.main:app --reload --port 8000

# Terminal 2 — RQ worker (needs Redis running)
python -m rq.cli worker --url redis://localhost:6379/0

# Open browser
open http://localhost:8000
```

### Tests
```bash
pytest tests/ -v
```

---

## Deploy

### Prerequisites
- VPS: 4 GB RAM minimum (Hetzner, DigitalOcean, etc.), Ubuntu 22.04 / 24.04
- Docker & Docker Compose plugin installed
- A domain with its A record pointing to the VPS IP

### 1. Clone and configure
```bash
git clone https://github.com/yourorg/autoqa.git
cd autoqa
cp .env.example .env
```

Edit `.env` and fill in every `CHANGEME` value:

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Generate FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `DOMAIN=yourdomain.com` and a strong `POSTGRES_PASSWORD`.

### 2. Harden the server
```bash
# Non-root user with SSH key auth (disable password SSH)
adduser autoqa
usermod -aG sudo autoqa
# Add your SSH public key to /home/autoqa/.ssh/authorized_keys
sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd

# Firewall
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable

# Unattended upgrades
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

### 3. Build and start
```bash
docker compose up -d --build
```

### 4. Run database migrations
```bash
docker compose exec web alembic upgrade head
```

### 5. Block private IP ranges from the worker (SSRF defense in depth)

After `docker compose up`, identify the worker subnet:

```bash
docker network inspect autoqa_worker_external | grep -A2 '"Subnet"'
# e.g. "Subnet": "172.18.0.0/16"
WORKER_SUBNET=172.18.0.0/16
```

Then apply host-level iptables rules to prevent the worker from
reaching any private/internal IP range:

```bash
sudo iptables -I DOCKER-USER -s $WORKER_SUBNET -d 10.0.0.0/8      -j DROP
sudo iptables -I DOCKER-USER -s $WORKER_SUBNET -d 172.16.0.0/12   -j DROP
sudo iptables -I DOCKER-USER -s $WORKER_SUBNET -d 192.168.0.0/16  -j DROP
sudo iptables -I DOCKER-USER -s $WORKER_SUBNET -d 169.254.0.0/16  -j DROP
sudo iptables -I DOCKER-USER -s $WORKER_SUBNET -d 127.0.0.0/8     -j DROP

# Persist rules across reboots
apt install -y iptables-persistent
netfilter-persistent save
```

> **Note:** The internal Docker network (`autoqa_internal`) allows the
> worker to reach Redis and Postgres. The worker_external network has
> outbound internet access for crawling, but iptables rules above block
> it from reaching private IP ranges.
>
> **SSRF & DNS Rebinding Protection:** The application applies Playwright
> request guards on outgoing URLs. To mitigate DNS rebinding where a domain
> resolves to a public IP during validation but a loopback/private IP during
> request dispatch, the host-level iptables rules above (or `scripts/block_worker_internal.sh`)
> are required to drop any packets from the worker to private subnets at the kernel network layer.

### 6. Postgres backups
```bash
# Daily pg_dump via cron (runs as root or autoqa user)
crontab -e
# Add:
0 3 * * * docker compose -f /path/to/autoqa/docker-compose.yml exec -T postgres \
  pg_dump -U autoqa autoqa | gzip > /backups/autoqa-$(date +\%Y\%m\%d).sql.gz

# Verify a backup restores:
zcat /backups/autoqa-YYYYMMDD.sql.gz | docker compose exec -T postgres psql -U autoqa autoqa
```

### 7. Log rotation
```bash
# /etc/logrotate.d/autoqa
/path/to/autoqa/security.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
```

### 8. Uptime monitoring
Add `https://yourdomain.com` to [UptimeRobot](https://uptimerobot.com) (free tier, 5-minute checks).

---

## Architecture

```
Browser → Caddy (HTTPS) → web (FastAPI) → Postgres
                                        → Redis → worker (Playwright)
                                                       ↓
                                                  artifacts/  (screenshots)
```

- **web** — FastAPI + Jinja2, user auth, wizard, reports. Internal network only.
- **worker** — RQ + Playwright, crawls verified sites. Dual network: internal (Redis/Postgres) + external (internet crawling). Host iptables block private ranges.
- **caddy** — Automatic TLS, reverse proxy, security headers.

---

## Pre-launch Checklist

- [ ] `SKIP_OWNERSHIP_FOR_DEV` is NOT set in production
- [ ] `http://localhost`, `http://127.0.0.1`, `http://169.254.169.254` are blocked
- [ ] Redirects to internal IPs are blocked
- [ ] Credentials are gone from DB after a run; grep logs for password (must find nothing)
- [ ] Limits work: 5 runs/day, concurrency, 25 pages, 5-minute timeout
- [ ] Terms and Privacy pages exist; authorization checkbox is required
- [ ] Account deletion removes all data and files
- [ ] Backups restore correctly (test one)
- [ ] `.env`, `auth/`, `artifacts/`, `*.db` are not in git
- [ ] Tested full flow on phone and desktop

---

## Security

- Passwords hashed with **Argon2**
- Test credentials encrypted at rest with **Fernet**; purged after each run
- **SSRF protection**: URL validation + DNS resolution + request-time guard
- **CSRF tokens** on all POST forms
- **Rate limiting** on login, register, and run endpoints (slowapi)
- Security events logged to `security.log` (no credentials ever logged)
- **Non-root Docker users** in both web and worker containers
- Worker network isolation + host iptables rules
