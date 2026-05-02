#!/usr/bin/env bash
# Database & runtime config backup (Design Doc §10.5).
#
# Backs up:
#   - SQLite DB at var/quant.db (or set $QUANT_DB_PATH)
#   - data/ (LLM runtime config, agent memory snapshots)
#   - logs/ (last 7 days only)
#
# Output: backups/quant_backup_<UTC-timestamp>.tar.gz
#
# Schedule via cron:
#   0 18 * * 1-5  /path/to/repo/infra/scripts/backup.sh
#
# Restore: tar -xzf <backup>.tar.gz -C /tmp/restore && bash infra/scripts/restore.sh /tmp/restore

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/quant_backup_${TS}.tar.gz"
DB_PATH="${QUANT_DB_PATH:-${REPO_ROOT}/var/quant.db}"

mkdir -p "${BACKUP_DIR}"
cd "${REPO_ROOT}"

echo "[backup] repo=${REPO_ROOT}"
echo "[backup] db=${DB_PATH}"
echo "[backup] out=${OUT}"

# Snapshot SQLite via .backup (consistent online copy)
SNAP_DIR="$(mktemp -d)"
trap 'rm -rf "${SNAP_DIR}"' EXIT
if [ -f "${DB_PATH}" ]; then
    sqlite3 "${DB_PATH}" ".backup '${SNAP_DIR}/quant.db'"
    echo "[backup] sqlite snapshot ok ($(du -h "${SNAP_DIR}/quant.db" | cut -f1))"
else
    echo "[backup] WARN: db not found at ${DB_PATH} — skipping"
fi

# Tarball: db snapshot + data/ + recent logs
TAR_INPUTS=()
[ -f "${SNAP_DIR}/quant.db" ] && TAR_INPUTS+=("-C" "${SNAP_DIR}" "quant.db")
[ -d "${REPO_ROOT}/data" ] && TAR_INPUTS+=("-C" "${REPO_ROOT}" "data")
if [ -d "${REPO_ROOT}/logs" ]; then
    # only files modified in last 7 days
    find "${REPO_ROOT}/logs" -type f -mtime -7 > "${SNAP_DIR}/logs.list" 2>/dev/null || true
    if [ -s "${SNAP_DIR}/logs.list" ]; then
        TAR_INPUTS+=("-C" "${REPO_ROOT}" "-T" "${SNAP_DIR}/logs.list")
    fi
fi

if [ ${#TAR_INPUTS[@]} -eq 0 ]; then
    echo "[backup] nothing to back up"
    exit 1
fi

tar -czf "${OUT}" "${TAR_INPUTS[@]}"
SIZE="$(du -h "${OUT}" | cut -f1)"
echo "[backup] done: ${OUT}  (${SIZE})"

# Retention: keep last 30 backups
ls -1t "${BACKUP_DIR}"/quant_backup_*.tar.gz 2>/dev/null | tail -n +31 | xargs -I{} rm -f {}
echo "[backup] retention applied (keep last 30)"
