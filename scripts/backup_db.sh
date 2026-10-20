#!/usr/bin/env bash
# AutoQA: Postgres daily backup script with age public-key encryption.
# Usage: AGE_RECIPIENT="age1..." ./backup_db.sh [/path/to/backup/dir]
set -euo pipefail

BACKUP_DIR="${1:-/var/backups/autoqa}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "${BACKUP_DIR}"

if [[ -n "${AGE_RECIPIENT:-}" ]]; then
    BACKUP_FILE="${BACKUP_DIR}/autoqa_${TIMESTAMP}.sql.gz.age"
    echo "Dumping and encrypting database to ${BACKUP_FILE} with age..."
    docker compose -f "${PROJECT_DIR}/docker-compose.yml" exec -T postgres \
        pg_dump -U "${POSTGRES_USER:-autoqa}" "${POSTGRES_DB:-autoqa}" | gzip | age -r "${AGE_RECIPIENT}" > "${BACKUP_FILE}"
else
    BACKUP_FILE="${BACKUP_DIR}/autoqa_${TIMESTAMP}.sql.gz"
    echo "Dumping database to ${BACKUP_FILE} (unencrypted: set AGE_RECIPIENT to enable age encryption)..."
    docker compose -f "${PROJECT_DIR}/docker-compose.yml" exec -T postgres \
        pg_dump -U "${POSTGRES_USER:-autoqa}" "${POSTGRES_DB:-autoqa}" | gzip > "${BACKUP_FILE}"
fi

chmod 600 "${BACKUP_FILE}"

# Keep last 14 days
find "${BACKUP_DIR}" -type f \( -name "autoqa_*.sql.gz" -o -name "autoqa_*.sql.gz.age" \) -mtime +14 -delete

echo "Backup complete: ${BACKUP_FILE}"
