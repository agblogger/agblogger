# Static Analysis and Related Quality Gates

`just check-static` is the repository's static-only gate. It runs, in order:

- `check-backend-static`
- `check-frontend-static`
- `check-vulture`
- `check-trivy`

Each target is fail-fast, and the default full gate `just check` runs `check-static` before the test suites.

## Backend (`check-backend-static`)

`check-backend-static` runs these commands:

- `uv run mypy backend/ cli/ tests/`
  - Strict Python type checking driven by `[tool.mypy]` in `pyproject.toml`.
  - Scope: backend, CLI, and tests.
- `uv run basedpyright backend/ cli/`
  - Second type-checking pass using BasedPyright.
  - Scope: backend and CLI runtime code only.
  - Config: `[tool.basedpyright]` in `pyproject.toml` uses `typeCheckingMode = "standard"` and excludes `.venv` plus `backend/migrations`.
- `uv run deptry .`
  - Dependency declaration hygiene for the Python project.
  - Config: `[tool.deptry]` and `[tool.deptry.per_rule_ignores]` in `pyproject.toml`.
- `uv run lint-imports`
  - Import-boundary enforcement via `.importlinter`.
  - Current contract: `backend.services`, `backend.filesystem`, `backend.models`, `backend.schemas`, `backend.crosspost`, `backend.sync`, and `backend.pandoc` must not import `backend.api`.
- `uv run ruff check backend/ cli/ tests/`
  - Python linting and security/style checks.
  - Config: `[tool.ruff]` and `[tool.ruff.lint]` in `pyproject.toml`.
- `uv run ruff format --check backend/ cli/ tests/`
  - Formatting compliance check for Python code.
- `uv export --format requirements.txt --no-dev --no-emit-project --frozen -o "$requirements_file"` then `uv run pip-audit --progress-spinner off --requirement "$requirements_file"`
  - Audits the locked runtime Python dependency set, not the dev toolchain.
  - The export omits dev dependencies and omits the editable local project itself, so the audit reflects shipped runtime dependencies from `uv.lock`.

## Frontend (`check-frontend-static`)

`check-frontend-static` runs these commands from `frontend/`:

- `npm run typecheck` (`tsc -b --noEmit`)
  - TypeScript type checking for the SPA.
  - Config: `frontend/tsconfig.app.json` is strict and enables checks such as `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`, `noUnusedLocals`, `noUnusedParameters`, and `noImplicitReturns`.
- `npm run lint` (`eslint .`)
  - Type-aware ESLint over TypeScript/React code.
  - Config: `frontend/eslint.config.js` extends `typescript-eslint` `strictTypeChecked`, `eslint-plugin-react-hooks`, and `eslint-plugin-react-refresh`.
- `npm run lint:deps` (`dependency-cruiser --config .dependency-cruiser.cjs src`)
  - Frontend module-boundary checks.
  - Current rules in `frontend/.dependency-cruiser.cjs`: no circular dependencies in `src`, and no runtime source imports from frontend test modules.
- `npm run lint:unused` (`knip --config knip.json --include dependencies,unlisted,unresolved`)
  - Dependency hygiene for the frontend package.
  - Config: `frontend/knip.json` scans `src/**/*.{ts,tsx}` and ignores a short allowlist of intentionally retained packages such as font packages and Stryker tooling.
- `npm run audit` (`npm audit --audit-level=high --omit=dev`)
  - Audits production npm dependencies only.

## Dead-Code Analysis (`check-vulture`)

- Command: `uv run vulture backend cli --exclude "backend/migrations" --min-confidence 80 --ignore-names "readline"`
- Purpose: detect likely unused Python runtime code.
- Scope: `backend/` and `cli/`, excluding migrations.
- Note: `readline` is explicitly ignored because the deployment CLI imports it for side effects.

## Trivy Repository Scan (`check-trivy`)

- Command: `trivy fs -q --scanners vuln,misconfig,secret,license --exit-code 1 .`
- Purpose: broad filesystem scan for vulnerabilities, misconfigurations, secrets, and license findings.
- Scope: repository filesystem subject to `trivy.yaml` skip rules.
- Severity policy: `trivy.yaml` enables `UNKNOWN`, `MEDIUM`, `HIGH`, and `CRITICAL`; `LOW` is intentionally suppressed.
- License policy: `trivy.yaml` ignores `OFL-1.1`.

## What `just check` Adds

Tests are intentionally separate from static analysis:

- `just test` runs `test-backend` and `test-frontend`
- `just test-backend coverage=true` adds backend/CLI coverage reporting
- `just test-frontend coverage=true` runs Vitest with coverage
- `just check` runs `just check-static` first, then `just test coverage=true`

This keeps static analysis available as a fast standalone gate while preserving a single full validation command.

## Extra and Noisy Gates

These checks are intentionally outside `just check-static` and `just check`:

- `just check-extra`
  - Runs `check-audit-full`, `checkov`, `check-gitleaks`, `check-codeql`, `check-semgrep`, `test-backend-slow`, and `check-snyk-deps`.
- `just check-audit-full`
  - Runs `npm audit` in `frontend/` without `--omit=dev`, so development dependencies are included.
- `just checkov`
  - Runs `uv run --with checkov checkov -f Dockerfile -f docker-compose.yml`.
- `just check-gitleaks`
  - Runs `gitleaks detect --source . --no-banner` using the repository config, which excludes `tests/`.
- `just check-gitleaks-full`
  - Runs a full Gitleaks scan with a temporary config extending the built-in defaults, including `tests/`.
- `just check-codeql`
  - Rebuilds and analyzes CodeQL databases for Python and JavaScript/TypeScript.
- `just check-semgrep`
  - Runs `uv run semgrep scan` with remote rulesets `p/ci`, `p/security-audit`, `p/secrets`, `p/owasp-top-ten`, `p/python`, `p/typescript`, `p/dockerfile`, `p/docker-compose`, `p/supply-chain`, `p/trailofbits`, plus the local `.semgrep.yml`.
  - Scope: `backend/`, `cli/`, `frontend/src/`, `Dockerfile`, and `docker-compose.yml`.
  - Exclusions: `tests`, frontend `__tests__`, and frontend `*.test.ts(x)` files.
- `just check-snyk-deps`
  - Runs `snyk test frontend` for frontend dependency scanning.
- `just check-snyk`
  - Runs `snyk code test` for repository source-code analysis.
- `just check-noisy`
  - Runs `check-snyk` and `check-gitleaks-full` sequentially and preserves a failing status if either reports issues.
