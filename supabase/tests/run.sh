#!/usr/bin/env bash
# Apply every migration to a throwaway Postgres 17 container and run the RLS tests.
#   bash supabase/tests/run.sh
# Needs Docker. Used locally and in CI; never touches the real Supabase project.
set -euo pipefail

cd "$(dirname "$0")/../.."
name="securepitch-dbtest-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" -e POSTGRES_PASSWORD=test postgres:17 >/dev/null
until docker exec "$name" pg_isready -U postgres -q; do sleep 1; done
sleep 1 # pg_isready can pass during the image's first-boot restart

psql() { docker exec -i "$name" psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }

echo "== Supabase stand-in"
psql < supabase/tests/supabase_stub.sql
for migration in supabase/migrations/*.sql; do
  echo "== $(basename "$migration")"
  psql < "$migration"
done
echo "== RLS and lifecycle tests"
# Results come through stderr (NOTICE and \warn); query output on stdout is noise.
psql < supabase/tests/rls_test.sql 2>&1 >/dev/null | sed -e 's/^psql:<stdin>:[0-9]*: //' -e 's/^NOTICE:  //'

echo "== Concurrent saves of one statement (double click)"
# Session A saves and holds its transaction open; session B saves the same statement meanwhile.
# B must wait for A, then replace A's draft: one live dossier, never two and never an error.
save="select public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('c3', 32), 40,
  '{}'::jsonb, tests.items('SRC'))"
printf 'begin;\n%s;\nselect pg_sleep(2);\ncommit;\n' "$save" | psql >/dev/null &
sleep 1
second=$(printf '%s ->> %s;\n' "$save" "'replaced_draft'" | psql -tA)
wait
live=$(psql -tA -c "select count(*) from public.dossiers where source_sha256 = repeat('c3', 32)")
if [ "$second" != "true" ] || [ "$live" != "1" ]; then
  echo "FAIL: concurrent saves left $live live dossiers (second replaced_draft: $second)" >&2
  exit 1
fi
echo "ok   the second save waited and replaced the first: one live dossier"
