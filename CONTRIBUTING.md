# Contributing to SecurePitch

## One-time setup per clone

Install [uv](https://docs.astral.sh/uv/) and pre-commit, then turn the hooks on:

```bash
# Windows (PowerShell or Git Bash)
py -m pip install --user uv pre-commit
py -m pre_commit install

# macOS, Linux, WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install pre-commit        # if `pre-commit` isn't found afterwards, run `uv tool update-shell`
pre-commit install
```

The hooks refuse commits on `main`, block secrets and Kenyan phone numbers (gitleaks), block statements, spreadsheets and photos outside the allowed folders, and lint Python with ruff.

**VS Code and Python:** after the engine's environment exists (`uv sync` in `services/engine`), run **Python: Select Interpreter** once and pick `services/engine/.venv`. VS Code remembers it per machine, which works on Windows (`.venv\Scripts`) and macOS/Linux (`.venv/bin`) alike.

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

- Real statements, rosters, receipt photos and phone numbers live only in `fixtures/private/` (git-ignored).
- Never paste real transaction data into issues, PRs, logs or screenshots.
- Secrets live in `.env` files and platform secret stores. Commit only `.env.example`.

If a secret is ever committed, tell the team immediately and rotate it. Deleting the commit is not enough.
