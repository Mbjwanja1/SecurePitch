# ADR 0002: The engine talks to Supabase over HTTPS only

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decider:** Chris Waweru, with the team

## Context

The build plan had the engine write to Postgres directly (`app/db.py` with psycopg and `DATABASE_URL`). Testing on 2026-11-03 showed the team's usual network **blocks outbound ports 5432 and 6543** (Postgres) and **7844** (Cloudflare Tunnel), while port 443 works. A neutral port-5432 test server also timed out, so this is the network, not Supabase. The Day 9 field venue and the demo venue could do the same. At the time of this decision, no engine code talks to the database yet, so nothing needs rework.

## Decision

1. **The engine reaches Supabase only over HTTPS (port 443)**, through the Data API (PostgREST) and Auth API with the secret key (`SUPABASE_SERVICE_ROLE_KEY`). No Postgres driver in the engine.
2. **Anything that must happen all-or-nothing is a Postgres function**, called over HTTPS (`POST /rest/v1/rpc/<name>`). Postgres runs each call as one transaction. The plan already puts the dossier state machine in one (`transition_dossier`); sealing and approval writes follow the same pattern.
3. **`DATABASE_URL` is for migrations only.** Run them from a network that allows port 5432 (a phone hotspot works), or paste the SQL into the Supabase SQL editor, which runs over HTTPS. `tools/check_infra.py` reports the database login as a **warning**, not a failure.
4. **On restrictive networks, the engine laptop uses a phone hotspot.** Only that laptop's own outbound connection matters (443 and 7844); the other devices can stay on the venue Wi-Fi. The tunnel runs with `--protocol http2`, which connects over **TCP** 7844 straight away on networks that block UDP. It doesn't avoid port 7844: tested 2026-11-03, the tunnel's connection in HTTP/2 mode goes to port 7844, and only the one-off quick-tunnel setup call uses 443. So a network that blocks TCP 7844 (as ours did) still needs the hotspot.

## Rules for code that uses the secret key

The secret key makes every request run as `service_role`, which bypasses row-level security, and for which `auth.uid()` is **null**. So the database can't tell which person is acting unless we tell it.

5. **Database functions called by the engine take the acting person and club as explicit parameters** (for example `p_actor`, `p_club`) and **check them inside the function**: that the actor belongs to the club, and has the role the action needs. They never rely on `auth.uid()`. `transition_dossier(p_dossier, p_to, p_actor)` is the model: it looks up `p_actor`'s role in the dossier's club and refuses anyone else.
6. **Every function sets its search path.** `SECURITY DEFINER` functions must use `set search_path = ''` and fully qualified names (`public.dossiers`, `auth.uid()`), so nobody can hijack them with a same-named object in another schema. Everything else is `SECURITY INVOKER` (the default). Every function's default `EXECUTE` permission is revoked, and granted back only to the roles that need it.
7. **The web app never trusts a club or user ID from the browser.** Before calling the engine, a Next.js route handler:
   1. gets the signed-in user from the Supabase session (`auth.getUser()`, server-side);
   2. loads the target dossier or club **with the user's own session**, so row-level security proves the user is a member (no row back = not a member = 403);
   3. sends the engine the user ID from the session and the club ID from that row, never values from the request body.

   The engine then passes them on as `p_actor` / `p_club`, and the database function checks them again (rule 5). A forged request has to get past both checks.

## Consequences

- Good: the engine works on any network that allows HTTPS, which removes a demo-day failure mode.
- Good: one protocol and one credential for the engine; no connection pool to manage.
- Good: multi-step rules live in the database next to the row-level security that guards them, so the web app and engine can't apply them differently.
- Cost: the engine can't run several separate queries inside a transaction it controls. Anything that needs that becomes a Postgres function, written as part of the migrations.
- Cost: the secret key bypasses row-level security, so engine code must scope every query by club itself, and rules 5–7 must hold in every function and route handler. Code review checks them.
- Risk register: add "venue network blocks 7844" (mitigation: hotspot for the engine laptop; pre-sealed dossier and recorded demo as fallback).
