---
sidebar_position: 0
title: Pagination Examples
description: HTTP pagination patterns for large datasets
---

# Pagination Examples

Examples demonstrating HTTP pagination patterns for efficiently fetching large datasets.

## Available Examples

- [Pagination Patterns](./pagination-patterns) - Page-number, cursor, offset, and retry patterns

## Working Playbooks

Complete, tested pagination playbooks in the repository:

- [basic/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/basic) - Page-number pagination
- [cursor/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/cursor) - Cursor-based pagination
- [offset/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/offset) - Offset-based pagination
- [retry/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/retry) - Pagination with error retry
- [max_iterations/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/pagination/max_iterations) - Safety limit testing
