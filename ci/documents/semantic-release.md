<h1 align="center" style="border-bottom: none;"> semantic-release</h1>

## How does it work?

### Commit message format

**semantic-release** uses the commit messages to determine the consumer impact of changes in the codebase.
Following formalized conventions for commit messages, **semantic-release** automatically determines the next [semantic version](https://semver.org) number, generates a changelog and publishes the release.

The table below shows which commit message gets you which release type when `semantic-release` runs (using the default configuration):

| Commit message | Release type |
| -------------- | ------------ |
| `fix: Fix some application bug` | Fix Release |
| `feat: Add some application feature` | Feature Release |
| `feat!: Make some breaking changes` | Breaking Release  |

### Example

Let's assume that the current release version is v1.0.0. The table below illustrates how the next release version is determined based on the commit message:

| Commit message | Next version |
| -------------- | ------------ |
| `fix: Fix some application bug` | v1.0.1 |
| `feat: Add some application feature` | v1.1.0 |
| `feat!: Make some breaking changes` | v2.0.0  |
