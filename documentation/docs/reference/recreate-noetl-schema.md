---
sidebar_position: 20
slug: /reference/recreate-noetl-schema
---

# Recreate NoETL Schema

This option allows you to fully recreate the NoETL database schema from scratch using the automation playbook. This is useful for development, testing, or resetting the environment.

## Command

Run the following command from the project root:

```bash
PGPASSWORD=demo bin/noetl run automation/setup/rebuild_schema.yaml
```

- `PGPASSWORD=demo` sets the database password for the demo user
- `bin/noetl run` executes the NoETL CLI
- `automation/setup/rebuild_schema.yaml` is the playbook that rebuilds the schema

## Notes
- This will drop and recreate all NoETL system tables in the target database.
- Only use in development or test environments. **Do not run in production.**
- See [automation/setup/rebuild_schema.yaml](../../automation/setup/rebuild_schema.yaml) for playbook details.

## Related Topics
- [Database Management](./database-management)
- [Local Development Setup](./local-development)
