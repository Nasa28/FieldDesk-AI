#!/usr/bin/env bash
# Insert a demo tenant + admin user, then print the tenant id so it can be
# fed straight into curl as X-Tenant-ID. Works against local psql if
# DATABASE_URL is set, or against the compose Postgres container otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQL=$(cat <<'EOF'
INSERT INTO tenants (name, slug)
VALUES ('Demo Field Co', 'demo')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO users (tenant_id, email, password_hash, full_name, role)
SELECT id, 'admin@demo.local', 'placeholder', 'Demo Admin', 'admin'
FROM tenants WHERE slug = 'demo'
ON CONFLICT (tenant_id, email) DO NOTHING;

SELECT id FROM tenants WHERE slug = 'demo';
EOF
)

if command -v psql >/dev/null 2>&1; then
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "DATABASE_URL is required when running against a local psql. Source .env or export it." >&2
    exit 1
  fi
  printf '%s' "${SQL}" | psql "${DATABASE_URL}" -At
else
  cd "${ROOT}"
  printf '%s' "${SQL}" | docker compose exec -T postgres \
    psql -U "${POSTGRES_USER:-fielddesk}" -d "${POSTGRES_DB:-fielddesk}" -At
fi
