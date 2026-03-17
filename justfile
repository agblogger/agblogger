# ── Bootstrap ───────────────────────────────────────────────────────

# Set up a fresh worktree: deps, env file, and local db directory
setup:
    @echo "── Backend: sync dependencies ──"
    uv sync --extra dev
    @echo "\n── Frontend: install dependencies ──"
    cd frontend && npm install
    @echo "\n── Environment: ensure .env exists ──"
    if [ -f .env ]; then echo ".env already exists (leaving as-is)"; else cp .env.example .env && echo "Created .env from .env.example"; fi
    @echo "\n── Database: ensure local dir exists ──"
    mkdir -p data/db
    @echo "\n✓ Fresh worktree setup complete"

# Remove generated artifacts, local runtime state, reports, and content
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf \
        .coverage \
        .hypothesis \
        .mypy_cache \
        .playwright-mcp \
        .pytest_cache \
        .ruff_cache \
        .venv \
        build \
        codeql-db \
        content \
        data \
        dist \
        frontend/.stryker-tmp \
        frontend/.tsbuildinfo \
        frontend/coverage \
        frontend/dist \
        frontend/node_modules \
        frontend/reports \
        htmlcov \
        node_modules \
        playwright-report \
        playwright-results \
        reports
    find . -type d -name '__pycache__' -prune -exec rm -rf {} +
    find . -maxdepth 2 -type d -name '*.egg-info' -prune -exec rm -rf {} +
    find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*$py.class' \) -delete
    @echo "\n✓ Generated artifacts removed"

# ── Quality checks ──────────────────────────────────────────────────

mutation_max_children := env("MUTATION_MAX_CHILDREN", "")
mutation_keep_artifacts := env("MUTATION_KEEP_ARTIFACTS", "false")
mutmut_version := "3.4.0"
zap_baseline_minutes := env("ZAP_BASELINE_MINUTES", "")
zap_full_minutes := env("ZAP_FULL_MINUTES", "")
zap_caddy_port := env("ZAP_CADDY_PORT", "8080")
local_caddy_port := env("LOCAL_CADDY_PORT", "8080")

# Run all static analysis checks (no tests)
check-static: check-backend-static check-frontend-static check-vulture check-trivy
    @echo "\n✓ Static checks passed"

# Run all test suites, excluding slow tests (pass coverage=true for coverage reports)
test coverage="false":
    just test-backend "{{ coverage }}"
    just test-frontend "{{ coverage }}"
    @echo "\n✓ Tests passed"

# Run full quality gate (static checks first, then tests with coverage enforcement)
check: check-static (test "true")
    @echo "\n✓ All checks passed"

# Run full frontend vulnerability audit (including dev dependencies)
check-audit-full:
    @echo "\n── Frontend: full vulnerability audit (including dev dependencies) ──"
    cd frontend && npm audit

# Run Checkov against container build/deploy manifests
checkov:
    @echo "\n── Infrastructure: Checkov scan (Dockerfile + docker-compose.yml) ──"
    uv run --with checkov checkov -f Dockerfile -f docker-compose.yml

# Run Gitleaks against the git repository, excluding tests/
check-gitleaks:
    @echo "\n── Repository: Gitleaks secret scan (excluding tests/) ──"
    gitleaks detect --source . --no-banner

# Run full Gitleaks history scan
check-gitleaks-full:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── Repository: Gitleaks full secret scan ──"
    cfg_file="$(mktemp)"
    trap 'rm -f "$cfg_file"' EXIT
    printf '[extend]\nuseDefault = true\n' > "$cfg_file"
    gitleaks detect --source . --config "$cfg_file" --no-banner --verbose

# Run Snyk open source dependency scan on the frontend
check-snyk-deps:
    @echo "\n── Snyk: open source dependency scan ──"
    snyk test frontend

# Run extra checks not covered by `check`
check-extra: check-audit-full checkov check-gitleaks check-codeql check-semgrep test-backend-slow check-snyk-deps
    @echo "\n✓ Extra checks passed"

# Run Snyk code analysis
check-snyk:
    @echo "\n── Snyk: code analysis ──"
    snyk code test

# Run noisy/offline-unfriendly checks
check-noisy:
    #!/usr/bin/env bash
    set -uo pipefail
    status=0
    just check-snyk || status=1
    just check-gitleaks-full || status=1
    if [ "$status" -eq 0 ]; then
        echo "\n✓ Noisy checks passed"
    else
        echo "\n✗ Noisy checks reported issues"
    fi
    exit "$status"

# ── Mutation testing ────────────────────────────────────────────────

# Targeted backend mutation gate for critical code paths
mutation-backend:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── Backend mutation testing (targeted gate) ──"
    args=()
    if [ "{{ mutation_keep_artifacts }}" = "true" ]; then args+=(--keep-artifacts); fi
    if [ -n "{{ mutation_max_children }}" ]; then args+=(--max-children "{{ mutation_max_children }}"); fi
    if [ "${#args[@]}" -eq 0 ]; then
        uv run --extra dev --with "mutmut=={{ mutmut_version }}" python -m cli.mutation_backend backend
    else
        uv run --extra dev --with "mutmut=={{ mutmut_version }}" python -m cli.mutation_backend backend "${args[@]}"
    fi

# Full backend+cli mutation sweep (nightly/full run)
mutation-backend-full:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── Backend mutation testing (full backend+cli sweep) ──"
    args=()
    if [ "{{ mutation_keep_artifacts }}" = "true" ]; then args+=(--keep-artifacts); fi
    if [ -n "{{ mutation_max_children }}" ]; then args+=(--max-children "{{ mutation_max_children }}"); fi
    if [ "${#args[@]}" -eq 0 ]; then
        uv run --extra dev --with "mutmut=={{ mutmut_version }}" python -m cli.mutation_backend backend-full
    else
        uv run --extra dev --with "mutmut=={{ mutmut_version }}" python -m cli.mutation_backend backend-full "${args[@]}"
    fi

# Targeted frontend mutation gate on high-impact flows
mutation-frontend:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── Frontend mutation testing (targeted gate) ──"
    cd frontend
    trap 'rm -rf .stryker-tmp/frontend' EXIT
    npm run mutation

# Full frontend mutation sweep (nightly/full run)
mutation-frontend-full:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── Frontend mutation testing (full sweep) ──"
    cd frontend
    trap 'rm -rf .stryker-tmp/frontend-full' EXIT
    npm run mutation:full

# Recommended PR mutation gate
mutation: mutation-backend mutation-frontend
    @echo "\n✓ Mutation gate passed"

# Comprehensive nightly mutation gate
mutation-full: mutation-backend mutation-backend-full mutation-frontend-full
    @echo "\n✓ Full mutation gate passed"

# Backend static checks: mypy, pyright, deptry, import-linter, ruff, pip-audit
check-backend-static:
    @echo "── Backend: type checking ──"
    uv run mypy backend/ cli/ tests/
    @echo "\n── Backend: pyright type checking ──"
    uv run basedpyright backend/ cli/
    @echo "\n── Backend: dependency hygiene ──"
    uv run deptry .
    @echo "\n── Backend: import contracts ──"
    uv run lint-imports
    @echo "\n── Backend: linting ──"
    uv run ruff check backend/ cli/ tests/
    @echo "\n── Backend: format check ──"
    uv run ruff format --check backend/ cli/ tests/
    @echo "\n── Backend: vulnerability audit ──"
    uv run pip-audit --progress-spinner off

# Backend tests, excluding slow tests (pass coverage=true for coverage report)
test-backend coverage="false":
    @echo "\n── Backend: tests ──"
    if [ "{{ coverage }}" = "true" ] || [ "{{ coverage }}" = "coverage=true" ]; then \
        uv run pytest tests/ -v -m "not slow" -n auto --cov=backend --cov=cli --cov-report=term-missing; \
    elif [ "{{ coverage }}" = "false" ] || [ "{{ coverage }}" = "coverage=false" ]; then \
        uv run pytest tests/ -v -m "not slow" -n auto; \
    else \
        echo "Invalid coverage option '{{ coverage }}' (use coverage=true|false)" >&2; \
        exit 1; \
    fi

# Backend slow tests only (marked @pytest.mark.slow)
test-backend-slow:
    @echo "\n── Backend: slow tests ──"
    uv run pytest tests/ -v -m slow -n auto

# Backend full gate (static + tests)
check-backend: check-backend-static test-backend

# Frontend static checks: tsc, eslint, dependency-cruiser, knip, npm audit
check-frontend-static:
    @echo "── Frontend: type checking ──"
    cd frontend && npm run typecheck
    @echo "\n── Frontend: linting ──"
    cd frontend && npm run lint
    @echo "\n── Frontend: dependency graph checks ──"
    cd frontend && npm run lint:deps
    @echo "\n── Frontend: dependency hygiene ──"
    cd frontend && npm run lint:unused
    @echo "\n── Frontend: vulnerability audit ──"
    cd frontend && npm run audit

# Frontend tests (pass coverage=true for coverage report)
test-frontend coverage="false":
    @echo "\n── Frontend: tests ──"
    if [ "{{ coverage }}" = "true" ] || [ "{{ coverage }}" = "coverage=true" ]; then \
        cd frontend && npm run test:coverage; \
    elif [ "{{ coverage }}" = "false" ] || [ "{{ coverage }}" = "coverage=false" ]; then \
        cd frontend && npm test; \
    else \
        echo "Invalid coverage option '{{ coverage }}' (use coverage=true|false)" >&2; \
        exit 1; \
    fi

# Frontend full gate (static + tests)
check-frontend: check-frontend-static test-frontend

# Dead-code analysis (Vulture), scoped to runtime Python code only.
check-vulture:
    @echo "── Runtime dead-code analysis (Vulture) ──"
    uv run vulture backend cli --exclude "backend/migrations" --min-confidence 80

# Runtime security-focused static analysis (Semgrep)
check-semgrep:
    @echo "── Runtime static security analysis (Semgrep) ──"
    uv run semgrep scan \
        --config p/ci \
        --config p/security-audit \
        --config p/secrets \
        --config p/owasp-top-ten \
        --config p/python \
        --config p/typescript \
        --config p/dockerfile \
        --config p/docker-compose \
        --config p/supply-chain \
        --config p/trailofbits \
        --config .semgrep.yml \
        --error \
        --quiet \
        backend/ cli/ frontend/src/ Dockerfile docker-compose.yml \
        --exclude tests \
        --exclude "frontend/src/**/__tests__" \
        --exclude "frontend/src/**/*.test.ts" \
        --exclude "frontend/src/**/*.test.tsx"

# Trivy security scans.
check-trivy:
    @echo "\n── Security scan (Trivy: all scanners/configured severities) ──"
    trivy fs -q \
        --scanners vuln,misconfig,secret,license \
        --exit-code 1 \
        .

# Internal: run a ZAP scan of the given mode with optional env-var fallback for minutes.
_zap mode env_minutes minutes:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "\n── DAST: OWASP ZAP {{ mode }} scan ──"
    minutes_value="{{ minutes }}"
    if [ -z "$minutes_value" ] && [ -n "{{ env_minutes }}" ]; then
        minutes_value="{{ env_minutes }}"
    fi
    args=(
        --project-dir "{{ justfile_directory() }}"
        --localdir "{{ localdir }}"
        --caddy-port "{{ zap_caddy_port }}"
    )
    if [ -n "$minutes_value" ]; then args+=(--minutes "$minutes_value"); fi
    python3 -m cli.zap_scan {{ mode }} "${args[@]}"

# OWASP ZAP baseline DAST scan against the local Caddy-served build.
zap-baseline minutes="": (_zap "baseline" zap_baseline_minutes minutes)

# OWASP ZAP full active DAST scan against the local Caddy-served build.
zap-full minutes="": (_zap "full" zap_full_minutes minutes)

zap: zap-baseline zap-full

# ── CodeQL ────────────────────────────────────────────────────────

# Create CodeQL databases for Python and JavaScript/TypeScript
setup-codeql:
    mkdir -p codeql-db
    @echo "── CodeQL: creating Python database ──"
    codeql database create codeql-db/python --language=python --source-root=. --overwrite
    @echo "\n── CodeQL: creating JavaScript database ──"
    codeql database create codeql-db/javascript --language=javascript --source-root=. --overwrite --command="cd frontend && npm run build"
    @echo "\n✓ CodeQL databases created in codeql-db/"

# Analyze CodeQL databases (security + quality suite)
codeql:
    @echo "── CodeQL: analyzing Python database ──"
    codeql database analyze codeql-db/python \
        codeql/python-queries:codeql-suites/python-security-and-quality.qls \
        --format=sarifv2.1.0 --output=codeql-db/python-results.sarif
    @echo "\n── CodeQL: analyzing JavaScript database ──"
    codeql database analyze codeql-db/javascript \
        codeql/javascript-queries:codeql-suites/javascript-security-and-quality.qls \
        --format=sarifv2.1.0 --output=codeql-db/javascript-results.sarif
    @echo "\n✓ CodeQL analysis complete — results in codeql-db/*.sarif"

# Rebuild CodeQL databases and analyze
check-codeql: setup-codeql codeql

# ── Build ─────────────────────────────────────────────────────────

# Create a full production build (frontend + backend dependency sync)
build:
    @echo "── Frontend: install dependencies ──"
    cd frontend && npm ci
    @echo "\n── Frontend: build ──"
    cd frontend && npm run build
    @echo "\n── Backend: sync dependencies ──"
    uv sync
    @echo "\n✓ Production build complete (frontend/dist/)"

# Build standalone CLI executable for the current platform
build-cli:
    uv run pyinstaller \
        --onefile \
        --name agblogger \
        --strip \
        --distpath dist/cli \
        --workpath build/cli \
        --specpath build/cli \
        --clean \
        --noconfirm \
        --exclude-module tkinter \
        --exclude-module test \
        --exclude-module unittest \
        --exclude-module pydoc \
        --exclude-module multiprocessing \
        --exclude-module sqlite3 \
        cli/sync_client.py

# Install the CLI client to prefix/bin (default: ~/.local/bin)
install prefix="$HOME/.local": build-cli
    mkdir -p "{{ prefix }}/bin"
    cp dist/cli/agblogger "{{ prefix }}/bin/agblogger"
    @echo "✓ Installed agblogger to {{ prefix }}/bin/"

# ── Deployment ──────────────────────────────────────────────

deploy:
    uv run agblogger-deploy

release level:
    uv run agblogger-release "{{ level }}"

# ── Development server ──────────────────────────────────────────────

backend_port := "8000"
frontend_port := "5173"
localdir := justfile_directory() / ".local"

# Start backend and frontend in the background (override ports: just start backend_port=9000 frontend_port=9173)
start:
    python3 -m cli.dev_server start --localdir "{{ localdir }}" --backend-port "{{ backend_port }}" --frontend-port "{{ frontend_port }}"

# Stop the running dev server
stop:
    python3 -m cli.dev_server stop --localdir "{{ localdir }}"

# Check if the dev server is healthy (backend API responds, frontend serves pages)
health:
    python3 -m cli.dev_server health --localdir "{{ localdir }}" --backend-port "{{ backend_port }}" --frontend-port "{{ frontend_port }}"

# Start the local Caddy-backed packaged app profile in the background
start-caddy-local:
    python3 -m cli.local_caddy start --localdir "{{ localdir }}" --caddy-port "{{ local_caddy_port }}"

# Stop the local Caddy-backed packaged app profile
stop-caddy-local:
    python3 -m cli.local_caddy stop --localdir "{{ localdir }}"

# Check if the local Caddy-backed packaged app profile is healthy
health-caddy-local:
    python3 -m cli.local_caddy health --caddy-port "{{ local_caddy_port }}"

# ── Developer commands (do not use unless you're human) ──────────────────────────────────────────

cloc:
    @echo "********************************************************************************"
    @echo "                              Source LOC count"
    @echo "********************************************************************************"
    @echo
    cloc --exclude-dir=__tests__ backend/ frontend/src/ cli/
    @echo
    @echo
    @echo "********************************************************************************"
    @echo "                              Tests LOC count"
    @echo "********************************************************************************"
    @echo
    cloc tests/ $(find frontend/src -type d -name __tests__)
