# Contributing to SecurePitch

## One-time setup per clone

```bash
py -m pip install --user pre-commit uv
py -m pre_commit install      # runs the hooks on every commit
```

The hooks refuse commits on `main`, block secrets and Kenyan phone numbers (gitleaks), block statements and spreadsheets outside `fixtures/synthetic/`, and lint Python with ruff.

## Workflow

1. Start from an up-to-date `main`:
   ```bash
   git switch main && git pull --ff-only
   git switch -c feat/engine-parser
   ```
2. Name branches `<type>/<area>-<topic>`, for example `feat/web-upload`, `fix/engine-masked-numbers`, `docs/dpia`, `chore/ci-cache`.
3. Write commits as [Conventional Commits](https://www.conventionalcommits.org/): `feat(engine): add balance-chain check`.
4. Keep pull requests small (under about 400 changed lines). Fill in the template.
5. CI must be green and one teammate must approve. Squash-merge, then delete the branch.
6. Every 1–2 days on a long branch, rebase on `main` (`git pull --rebase origin main`).

## Data rules

- Real statements, rosters and phone numbers live only in `fixtures/private/` (git-ignored).
- Never paste real transaction data into issues, PRs, logs or screenshots.
- Secrets live in `.env` files and platform secret stores. Commit only `.env.example`.

If a secret is ever committed, tell the team immediately and rotate it. Deleting the commit is not enough.
