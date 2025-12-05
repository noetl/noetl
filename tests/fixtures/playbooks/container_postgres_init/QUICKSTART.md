# Container PostgreSQL Init - Quick Reference

## Overview
Container-based PostgreSQL initialization demonstrating Kubernetes Job execution with NoETL.

## Quick Start

```bash
# 1. Build and load image
cd tests/fixtures/playbooks/container_postgres_init
./build.sh

# Or use task
task test:container:build-image

# 2. Run full test
task test:container:full

# 3. Verify results
task test:container:verify
```

## File Structure

```
container_postgres_init/
├── container_postgres_init.yaml    # Main playbook
├── Dockerfile                      # Container image
├── build.sh                        # Build helper script
├── README.md                       # Full documentation
├── QUICKSTART.md                   # This file
├── scripts/
│   ├── init_schema.sh             # Create schema
│   ├── create_tables.sh           # Create tables
│   └── seed_data.sh               # Insert data
└── sql/
    ├── create_schema.sql          # Schema SQL
    ├── create_tables.sql          # Table DDL
    └── seed_data.sql              # Data inserts
```

## Task Commands

| Task | Alias | Description |
|------|-------|-------------|
| `test:container:build-image` | `tcbi` | Build and load image into Kind |
| `test:container:register` | `tcr` | Register playbook |
| `test:container:execute` | `tce` | Execute playbook |
| `test:container:verify` | `tcv` | Verify results in DB |
| `test:container:cleanup` | `tcc` | Drop test schema |
| `test:container:full` | `tcf` | Full workflow |

## Playbook Steps

1. **verify_postgres_connection** - Test DB connectivity
2. **run_schema_creation** - Create schema via container job
3. **run_table_creation** - Create tables via container job
4. **seed_test_data** - Insert sample data via container job
5. **verify_data** - Query and verify results
6. **cleanup_test_data** - Drop schema (optional)

## Expected Results

After successful execution:

- Schema: `container_test`
- Tables: `customers` (10 rows), `products` (15 rows), `orders` (5 rows), `order_items` (varies)
- Views: `order_summary`
- Execution log entries: 3 (init_schema, create_tables, seed_data)

## Key Features Demonstrated

✓ Kubernetes Job execution from NoETL worker
✓ Credential injection via environment variables
✓ Script file mounting (ConfigMap)
✓ SQL file mounting (multiple files)
✓ Container resource limits
✓ Job cleanup after completion
✓ Pod logs collection and reporting
✓ Multi-step workflow coordination

## Environment Variables Passed

- `PGHOST`, `PGPORT`, `PGDATABASE` - Connection details
- `PGUSER`, `PGPASSWORD` - Credentials (from secrets)
- `EXECUTION_ID` - NoETL tracking ID
- `SCHEMA_NAME` - Target schema

## Troubleshooting

**Image not found in cluster?**
```bash
kind load docker-image noetl/postgres-container-test:latest --name noetl
```

**Job failed?**
```bash
kubectl get jobs -n noetl
kubectl logs -n noetl job/<job-name>
```

**No data in tables?**
```bash
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "\dt container_test.*"
```

## More Information

See [README.md](README.md) for complete documentation including:
- Architecture diagrams
- Detailed step-by-step instructions
- Troubleshooting guide
- Best practices
- Related documentation links
