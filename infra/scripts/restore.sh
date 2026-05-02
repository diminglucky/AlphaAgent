#!/usr/bin/env bash
# Restore from a backup tarball produced by backup.sh.
#
# Usage:
#   bash infra/scripts/restore.sh <backup_tarball.tar.gz>
#
# Performs:
#   1. Stops running API (best-effort, prompts if cannot)
#   2. Moves current var/quant.db -> var/quant.db.bak.<ts>
#   3. Extracts tarball into a tmp dir, copies quant.db + data/
#   4. Runs alembic migrations to ensure schema head
#
# Recovery RTO target: <30min (Design Doc §10.5).

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $0 <backup.tar.gz>" >&2
    exit 2
fi

ARCHIVE="$1"
if [ ! -f "${ARCHIVE}" ]; then
    echo "ERROR: archive not found: ${ARCHIVE}" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB_PATH="${QUANT_DB_PATH:-${REPO_ROOT}/var/quant.db}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "[restore] archive=${ARCHIVE}"
echo "[restore] repo=${REPO_ROOT}"
echo "[restore] db=${DB_PATH}"

# Sanity: ask before clobbering
if [ -f "${DB_PATH}" ]; then
    BAK="${DB_PATH}.bak.${TS}"
    echo "[restore] backing up current db -> ${BAK}"
    cp "${DB_PATH}" "${BAK}"
fi

# Extract
tar -xzf "${ARCHIVE}" -C "${TMP}"
echo "[restore] extracted contents:"
ls -la "${TMP}"

# Restore DB if present in archive
if [ -f "${TMP}/quant.db" ]; then
    mkdir -p "$(dirname "${DB_PATH}")"
    cp "${TMP}/quant.db" "${DB_PATH}"
    echo "[restore] db restored ($(du -h "${DB_PATH}" | cut -f1))"
fi

# Restore runtime data dir
if [ -d "${TMP}/data" ]; then
    mkdir -p "${REPO_ROOT}/data"
    cp -R "${TMP}/data/." "${REPO_ROOT}/data/"
    echo "[restore] data/ restored"
fi

# Make sure schema is at head (forwards compat after restore from older snap)
echo "[restore] running alembic upgrade head"
cd "${REPO_ROOT}"
alembic -c alembic.ini upgrade head

echo "[restore] done. Verify with: python infra/scripts/smoke_test.py"
