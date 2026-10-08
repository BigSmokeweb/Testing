#!/usr/bin/env bash
# AutoQA: Postgres daily backup script.
# Usage: ./backup_db.sh [/path/to/backup/dir]
set -euo pipefail

BACKUP_DIR="${1:-/var/backups/autoqa}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/autoqa_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "Dumping database to ${BACKUP_FILE}..."
docker compose -f "${PROJECT_DIR}/docker-compose.yml" exec -T postgres \
    pg_dump -U autoqa autoqa | gzip > "${BACKUP_FILE}"

# Keep last 14 days
find "${BACKUP_DIR}" -type f -name "autoqa_*.sql.gz" -mtime +14 -delete

echo "Backup complete: ${BACKUP_FILE}"
