# Contributing

Thank you for your interest. This repository is part of an institutional digitisation initiative at the **Thuringian University and State Library (ThULB)**. Contributions, bug reports, and suggestions are welcome.

## Before you contribute

- Read [README.md](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) to understand the monorepo layout and the phase-based development model.
- For non-trivial changes, **open an issue first** so we can discuss scope before you invest implementation time.

## Reporting bugs

Use the **Bug report** issue template. Include:

- Browser, OS, Node version, Python version.
- Steps to reproduce.
- Expected vs. observed behavior.
- Relevant log output from the backend terminal (no API keys, please).
- Phase number if you can identify which feature is involved (Phase 8 = validation rules, Phase 9 = Verify cockpit, Phase 10 = Clean view, Phase 11 = Authority reconciliation — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the phase index).

## Suggesting features

Use the **Feature request** issue template. Include:

- The problem the feature solves (who, what, why).
- A proposed approach if you have one (optional).
- Anything you've ruled out and why.

Note: the roadmap is structured as numbered phases. A feature suggestion may become a new phase if accepted; the [.planning/](.planning/) directory shows how previous phases were scoped from discussion to verification.

## Pull requests

1. Fork the repository.
2. Create a branch from `main`: `git checkout -b feat/your-feature` or `fix/your-bug`.
3. Make your changes. Follow the existing patterns:
   - **Code style:** match the surrounding file. No formatter is enforced repository-wide; consistency within touched files is the rule.
   - **Commit messages:** conventional commits-ish (`feat(scope):`, `fix(scope):`, `docs(scope):`). See `git log` for recent examples.
   - **Atomic commits:** one logical change per commit.
4. Verify before pushing:
   - `npm run typecheck` — TypeScript across both apps.
   - `npm run lint` — if you've enabled lints (turbo task is wired).
   - Backend: run `python -c "import app.main"` inside `apps/backend/` to confirm import-clean.
5. Open a PR against `main`. Describe what changed and why. Reference any issue numbers.

## Code review expectations

This is a small institutional project. PRs are reviewed when reviewer time is available. We prioritise:

- **Correctness** — does it do what it claims, and only what it claims?
- **Scope discipline** — one PR, one logical change. Drive-by refactors should be separate.
- **Cross-phase implications** — many cross-phase wiring breaks have been caught in milestone audits. If your change touches schemas, types, or data shapes, please call out which phases consume them.
- **No secrets** — `.env` and any other file with credentials must never appear in a PR.

## Local development

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md). Briefly:

```bash
npm install
cp .env.example .env  # Then edit and set OPENROUTER_API_KEY
npm run dev
```

## Code of conduct

Be respectful. Assume good faith. This project supports cultural heritage work — that work is done by humans who deserve courtesy in technical discussion. We'll add a formal Code of Conduct if the project grows enough to need one.

## License

By contributing, you agree your contributions will be licensed under the MIT License (see [LICENSE](LICENSE)).
