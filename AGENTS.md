# Repository Guidelines

AgBlogger is a markdown-first blogging platform where markdown files with YAML front matter are the source of truth for all post content and metadata.

## Architecture

**IMPORTANT** Read @docs/arch/index.md for architecture overview. **ALWAYS** read ALL files under docs/arch/ that are relevant to your current task. Read other files in docs/arch/ when you need deeper understanding of application architecture. Update docs/arch/*.md (all relevant files) whenever architecture changes – always keep these files up-to-date with the codebase.

The primary purpose of architecture docs in docs/arch/*.md is to provide agents with a quick but comprehensive overview of the system's architecture and the codebase. Treat the docs as an onboarding guide. When updating, do not add unnecessary brittle implementation details, but do include info on where to find relevant codebase references.

## Build, Test, and Development Commands

```bash
just start            # Start backend (:8000) + frontend (:5173) in the background (run unsandboxed)
just stop             # Stop the running dev server
just health           # Check if dev server is healthy (backend + frontend)
just check            # Full gate: static checks first, then tests (excludes slow tests)
just check-extra      # Extra dependency/security checks + slow backend tests
just test             # Test-only gate: backend + frontend tests (excludes slow tests)
just check-backend    # Backend static checks + backend tests
just test-backend     # Backend tests only (excludes slow tests)
just check-frontend   # Frontend static checks + frontend tests
just test-frontend    # Frontend tests only
```
All `just` commands must be run unsandboxed.

Always start a dev server with `just start` (unsanboxed). Remember to stop a running dev server with `just stop` when finished.

## Coding Style & Naming Conventions

### Python (backend/, cli/, tests/)

- Formatting: ruff (line length 100)
- Typing: strict discipline (`mypy` strict + `basedpyright`); modern union syntax (`str | None`, `dict[str, Any]`, `list[str]`)
- Do NOT use `type: ignore` comments. If ignoring a type rule is necessary, ALWAYS ask the user for permission and explain why.
- Do NOT use `noqa` comment. If ignoring a lint rule is necessary, ALWAYS ask the user for permission and explain why.
- Do not use `fmt: skip` or `fmt: off` comments. If ignoring the formatter is necessary, ask the user for permission and explain why.

### TypeScript (frontend/src/)

- Formatting: ESLint with typescript-eslint (type-checked rules); avoid `eslint-disable-line`
- Naming & style: `camelCase.ts` utilities/stores; `fetch` prefix for API functions, `handle` prefix for event handlers; Tailwind with semantic color tokens

## Testing Guidelines

- **IMPORTANT**: Every new feature should include tests that verify its correctness at the appropriate levels (unit, integration, and possibly system level).
- **IMPORTANT**: Follow Test Driven Development (TDD). Write failing tests first, implement changes later to make the tests pass.
- **IMPORTANT**: For every bug found, add a regression test that fails because of the bug, then fix the bug and ensure the test passes.
- Use property-based testing (Hypothesis, fast-check) for deterministic logic. Abstract high-invariant logic into independent pure functions to enable property-based testing.
- Avoid brittle tests. Test user workflows, not implementation details.
- Backend tests which take more than 1s to run should be marked @pytest.mark.slow. If a fixture setup takes more than 1s, the entire group of tests using that fixture should be marked @pytest.mark.slow.
- Coverage target 80%, branches 70%.

## Commit & Pull Request Guidelines

- Commit format: `type: subject` in imperative lowercase (e.g., `feat: add transfer flow`).
- PR title format same as commit format (`type: subject`).
- PR descriptions should summarize changes, rationale and impact. Do not summarize validation or testing. Unless the PR updates documentation only, do not describe documentation changes.
- Keep commits focused; avoid mixing unrelated changes.
- Use `git add`, `git commit`, `git merge`, etc. Do NOT use the `-C` option with `git`.

## Reliability Guidelines

- The server may NEVER crash. We are aiming for a production-grade high-reliability server with 100% uptime.
- No exceptions may crash the server. All errors should be handled and logged server-side.
- Check for race conditions: missing or incorrect locking, non-atomic compound operations, check-then-act patterns, improper initialization.

## Security Guidelines

- All exceptions need to be handled gracefully, especially errors originating from interaction with external services (network, database, pandoc, git, filesystem). Never silently ignore exceptions.
- Never expose *internal* server error details to clients: return a generic error message to clients while keeping detailed logging server-side.
- Business logic errors (input validation, invalid action, etc.) are NOT internal server errors: clients should be informed what went wrong when the error is a direct result of invalid user action or input.
- Any security-sensitive bug fix or feature change must include failing-first regression tests that cover abuse paths, not only happy paths.
- **IMPORTANT**: Read docs/guidelines/security.md for security guidelines before making any changes related to authentication, authorization, input validation, sanitization, or error handling.

## Instructions

- **IMPORTANT**: Keep ALL files under docs/arch/ in sync with the codebase. Update them after any frontend or backend architecture changes, addition of major new features, workflow changes.
- Avoid code duplication. Abstract common logic into parameterized functions.
- Do NOT try to circumvent static analysis tools. Adapt the code to pass `just check` properly - do not ignore checks or suppress rules. If you absolutely need to bypass a static analysis tool, ALWAYS ask the user for approval and explain why this is necessary.
- When saving a plan, put it in docs/plans/. 
- When saving a spec or design doc, put it in docs/specs/.
- When finished, verify with `just check`.
