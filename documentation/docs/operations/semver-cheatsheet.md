---
id: semver-cheatsheet
title: SemVer release, commit messages, and branch names
sidebar_label: SemVer Cheatsheet
description: A practical guide to mapping changes to SemVer using Conventional Commits and clear branch naming.
---

# SemVer release, commit messages, and branch names

Semantic Versioning (SemVer) uses MAJOR.MINOR.PATCH (e.g., 2.1.4). The goal of this guide is to make it easy to consistently map a day‑to‑day work (commits and branches) to the correct version bump.

## Summary

- PATCH (x.x.1): bug fixes — use `fix:`
- MINOR (x.1.x): backward‑compatible features — use `feat:`
- MAJOR (1.x.x): breaking changes — mark with `!` after type or add a `BREAKING CHANGE:` footer
- Non-release changes: `docs:`, `chore:`, `refactor:`, `style:`, `test:`, `ci:`, `build:`, `perf:` (usually no version bump; may be configured)


## 1. Commit messages (Conventional Commits)

### Structure

```
<type>(<scope>): <short description>

[optional body]

[optional footer(s)]
```

- type: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- scope: optional, a short area name (e.g., `auth`, `api`, `ui`); use kebab-case if needed
- description: imperative, sentence‑style, ~50 characters if possible

### How commit types map to SemVer

- `feat`: triggers MINOR version bump
- `fix`: triggers PATCH version bump
- `type!`: any type marked with `!` indicates a MAJOR bump
- `BREAKING CHANGE:` footer also indicates a MAJOR bump
- Other types (`docs`, `chore`, `refactor`, `style`, `test`, `ci`, `build`, `perf`): no version bump by default

### Breaking changes (MAJOR)

Use either of the following:

- Inline:
  ```
  feat!: migrate to v2 authentication
  ```
- Footer:
  ```
  refactor(auth): replace JWT library
  
  BREAKING CHANGE: login() now requires tenantId.
  ```

Be explicit in the body/footer about what breaks and how to migrate.

### Good commit examples

```
fix(auth): handle expired refresh token
feat(api): add user profile endpoint
feat(ui)!: remove legacy sidebar navigation

BREAKING CHANGE: The sidebar prop layoutMode was removed.

refactor(db): simplify transaction handling
docs(readme): clarify local setup steps
```

### Optional notes

- Keep subject lines short and imperative: "add", "fix", "remove", not "adds", "fixed"
- Wrap body at ~72 chars when possible
- Use `revert: <subject>` with a body referencing the commit hash to revert a change

## 2. Branch naming conventions

### Short‑lived work branches

- `feat/<summary>` — new features that may lead to MINOR bump
- `fix/<summary>` — bug fixes that may lead to PATCH bump
- `chore/<summary>`, `docs/<summary>`, `refactor/<summary>`, `perf/<summary>`, `ci/<summary>`, `test/<summary>`, `build/<summary>`

#### Examples

- `feat/user-avatars`
- `fix/login-timeout`
- `refactor/data-fetching`
- `docs/update-api-usage`

### Release and maintenance branches

- `release/vX.Y.Z` — to stage a specific release (e.g., `release/v1.2.0`)
- `hotfix/vX.Y.Z` — urgent fixes on production (e.g., `hotfix/v1.1.1`)
- `maintenance/X.Y` — long‑lived branch for backports (e.g., `maintenance/1.2`)

### Tips

- For large breaking efforts, consider `feat/breaking/<summary>` as a warning signal to reviewers
- Keep branch names kebab-case and concise

## 3. Example workflow

1. Start a branch
   - `feat/user-avatars` from `main` (or from `maintenance/1.2` if backporting)
2. Commit with Conventional Commits
   - `feat(ui): add avatar component`
   - `fix(ui): handle missing image url`
3. Open a PR
   - If using squash merges, set the PR title in Conventional Commit style; it becomes the final commit message
4. Merge to `main`
   - Automation parses commit(s) and calculates the next version:
     - Contains `feat` => MINOR bump
     - Contains `fix` only => PATCH bump
     - Any breaking (`!`) or `BREAKING CHANGE` => MAJOR bump

### Rule of thumb when multiple types are present

- The highest impact wins: MAJOR > MINOR > PATCH

## 4. Pre‑releases

Use SemVer pre‑release identifiers when releasing candidates:

- `v2.0.0-alpha.1`, `v2.0.0-beta.2`, `v2.0.0-rc.1`

### General guidance

- Alpha: early testing; changes still likely
- Beta: feature complete; stabilizing
- RC: release candidate; only critical fixes

You can maintain pre‑releases on a release branch (e.g., `release/v2.0.0`) until stable is ready.

## 5. PR titles and merge strategy

- Prefer squash‑and‑merge to keep a clean history; ensure the PR title is a valid Conventional Commit
- If merging multiple commits, ensure at least one commit reflects the intended bump (`feat`/`fix`/`!` or `BREAKING CHANGE`)
- Include migration notes in the PR body for breaking changes

## 6. Quick reference table

| Change Type | SemVer Impact | Commit Prefix            | Example                                 |
|-------------|---------------|--------------------------|-----------------------------------------|
| Breaking    | MAJOR         | `type!:` or `BREAKING CHANGE:` | `feat!: remove legacy API`            |
| Feature     | MINOR         | `feat:`                  | `feat: add search bar`                   |
| Fix         | PATCH         | `fix:`                   | `fix: handle null pointer`               |
| Docs/Chore  | None (default)| `docs:`/`chore:`         | `docs: update readme`                    |
| Refactor    | None (default)| `refactor:`              | `refactor: simplify mapper`              |
| Perf        | None (default)| `perf:`                  | `perf: cache dashboard queries`          |
| Tests       | None (default)| `test:`                  | `test: add e2e for login`                |
| Build/CI    | None (default)| `build:`/`ci:`           | `ci: run tests on pull requests`         |

## 7. FAQs and gotchas

- Do docs/test changes trigger a release?
  - Not by default. You can configure tooling to publish on other types if desired.
- How do I mark a breaking change?
  - `type!` in the subject or `BREAKING CHANGE:` in the footer (both are recognized)
- What if my PR has both feat and fix commits?
  - The highest impact applies — at least a MINOR bump
- How should I choose scopes?
  - Use a short area name (service, package, feature) like `auth`, `api`, `ui`; kebab-case if multiword
- How detailed should the body be?
  - Explain the why, outline the approach, and note migration steps for breaking changes

### Copy‑paste commit templates

#### Subject only (simple)
```
type(scope): short description
```

#### With body and breaking change
```
type(scope): short description

Longer explanation of the motivation and approach.
Include links to issues if helpful.

BREAKING CHANGE: What changed, why it breaks, and how to migrate.
```

### Recommended branch prefixes

- `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`, `perf/`, `ci/`, `test/`, `build/`
- `release/vX.Y.Z`, `hotfix/vX.Y.Z`, `maintenance/X.Y`

By following this cheatsheet, your history becomes machine‑readable and human‑friendly, enabling reliable automated SemVer releases.
