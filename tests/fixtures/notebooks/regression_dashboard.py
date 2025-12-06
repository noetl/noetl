#%% md
# NoETL Regression Runs — Execution Analysis Dashboard
#
# This notebook-style script connects to Postgres (schema `noetl`) and provides
# an analysis view for playbook executions — tailored for regression tests
# like `tests/fixtures/playbooks/regression_test/master_regression_test.yaml`.
#
# Use it to:
# - Inspect recent runs and their final statuses
# - Drill into failures by step and error messages
# - Analyze retries and slow steps
# - Visualize a single run timeline (Gantt)
#
# Requirements (install inside JupyterLab or your local env):
# ```
# pip install pandas sqlalchemy psycopg2-binary plotly
# ```

#%%
import os
import json
import datetime as dt
from pathlib import Path

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text
import plotly.express as px

try:
    from IPython.display import display
except Exception:  # pragma: no cover - harmless outside IPython
    def display(*args, **kwargs):  # fallback
        for a in args:
            print(a)

#%% md
## Configuration
#
# The script tries to read Postgres parameters from
# `tests/fixtures/credentials/pg_local.json`. If not found, it falls back to
# `postgresql://demo:demo@localhost:54321/demo_noetl`.
#
# You can override via environment variables: `PGHOST`, `PGPORT`, `PGUSER`,
# `PGPASSWORD`, `PGDATABASE`.

#%%
def find_repo_root(start: Path) -> Path:
    cur = start
    for _ in range(10):
        candidate = cur / 'tests' / 'fixtures' / 'credentials' / 'pg_local.json'
        if candidate.exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


REPO = find_repo_root(Path.cwd())
cred_path = REPO / 'tests' / 'fixtures' / 'credentials' / 'pg_local.json'
cfg = None
if cred_path.exists():
    try:
        cfg = json.loads(cred_path.read_text())
    except Exception as e:
        print('Failed to read pg_local.json:', e)

host = os.getenv('PGHOST') or (cfg and cfg.get('data', {}).get('db_host')) or 'localhost'
port = int(os.getenv('PGPORT') or (cfg and cfg.get('data', {}).get('db_port') or 54321))
user = os.getenv('PGUSER') or (cfg and cfg.get('data', {}).get('db_user')) or 'demo'
password = os.getenv('PGPASSWORD') or (cfg and cfg.get('data', {}).get('db_password')) or 'demo'
database = os.getenv('PGDATABASE') or (cfg and cfg.get('data', {}).get('db_name')) or 'demo_noetl'

# If the detected host is the in-cluster DNS and you're running locally, you may want to override
# to localhost:54321. Leave as-is when running inside the Kind JupyterLab.
pg_dsn = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
print('Primary DSN:', pg_dsn)

# Attempt primary connection; on failure, fallback to localhost:54321 which is mapped by Kind.
def create_engine_with_fallback(primary_dsn: str):
    try:
        eng = sa.create_engine(primary_dsn, pool_pre_ping=True, future=True)
        with eng.connect() as conn:
            # simple check
            conn.execute(text('select 1'))
        print('Connected with primary DSN')
        return eng
    except Exception as e:
        print('Primary DSN failed, trying localhost fallback:', e)
        fallback_dsn = f"postgresql+psycopg2://{user}:{password}@localhost:54321/{database}"
        print('Fallback DSN:', fallback_dsn)
        eng = sa.create_engine(fallback_dsn, pool_pre_ping=True, future=True)
        with eng.connect() as conn:
            conn.execute(text('select 1'))
        print('Connected with fallback DSN')
        return eng

engine = create_engine_with_fallback(pg_dsn)
with engine.connect() as conn:
    print('DB time:', list(conn.execute(text('select now()')))[0][0])

#%% md
## Parameters
#
# - `PLAYBOOK_PATH` — filter for catalog path (substring match).
# - `HOURS_BACK` — lookback window for runs.
# - `LIMIT` — max number of executions to consider in overview.

#%%
PLAYBOOK_PATH = 'tests/fixtures/playbooks/regression_test/master_regression_test.yaml'
HOURS_BACK = 72
LIMIT = 200

lookback_from = dt.datetime.utcnow() - dt.timedelta(hours=HOURS_BACK)
lookback_from

#%% md
## Data model reference (from `noetl` schema)
#
# - `noetl.catalog(catalog_id, path, ...)`
# - `noetl.event(execution_id, event_id, catalog_id, created_at, event_type, node_name, node_type, status, duration, error, ...)`
# - `noetl.workflow(execution_id, step_id, step_name, step_type, ...)` (structure of steps)
# - `noetl.workload(execution_id, data)` (workload input)
# - `noetl.vars_cache(execution_id, var_name, var_value, ...)` (runtime variables)
#
# We derive a run's final status by taking the last event per `execution_id` by `created_at`.

#%%
sql_overview = text(
    """
    with filtered as (
      select e.*, c.path
      from noetl.event e
      join noetl.catalog c on c.catalog_id = e.catalog_id
      where e.created_at >= :from_ts
        and (:path_substr is null or c.path like '%' || :path_substr || '%')
    ), last_event as (
      select execution_id,
             max(created_at) as last_at
      from filtered
      group by execution_id
    ), final as (
      select f.execution_id, f.path, f.status, f.created_at, f.duration
      from filtered f
      join last_event le
        on f.execution_id = le.execution_id and f.created_at = le.last_at
    )
    select *
    from final
    order by created_at desc
    limit :lim
    """
)

with engine.connect() as conn:
    df_overview = pd.read_sql(sql_overview, conn, params={'from_ts': lookback_from, 'path_substr': PLAYBOOK_PATH, 'lim': LIMIT})

print('Recent runs:')
display(df_overview.head(10))

#%%
# KPIs
total = len(df_overview)
succ = int((df_overview['status'] == 'success').sum()) if total else 0
fail = int((df_overview['status'] == 'error').sum()) if total else 0
other = total - succ - fail
median_dur = float(df_overview['duration'].median()) if total else None
print({'total_runs': total, 'success': succ, 'error': fail, 'other': other, 'median_duration_sec': median_dur})

#%%
# Failures by step (top offenders)
sql_fail_by_step = text(
    """
    with filtered as (
      select e.*, c.path
      from noetl.event e
      join noetl.catalog c on c.catalog_id = e.catalog_id
      where e.created_at >= :from_ts
        and (:path_substr is null or c.path like '%' || :path_substr || '%')
    )
    select node_name, count(*) as error_count
    from filtered
    where status = 'error'
    group by node_name
    order by error_count desc
    limit 50
    """
)

with engine.connect() as conn:
    df_fail = pd.read_sql(sql_fail_by_step, conn, params={'from_ts': lookback_from, 'path_substr': PLAYBOOK_PATH})

fig = px.bar(df_fail, x='node_name', y='error_count', title='Failures by step (last runs)', text='error_count')
fig.update_layout(xaxis={'categoryorder': 'total descending'})
fig.show()

#%%
# Slowest steps (median duration)
sql_slowest = text(
    """
    with filtered as (
      select e.*, c.path
      from noetl.event e
      join noetl.catalog c on c.catalog_id = e.catalog_id
      where e.created_at >= :from_ts
        and (:path_substr is null or c.path like '%' || :path_substr || '%')
        and e.duration is not null
        and e.node_name is not null
    )
    select node_name,
           percentile_cont(0.5) within group (order by duration) as p50,
           percentile_cont(0.9) within group (order by duration) as p90,
           count(*) as n
    from filtered
    where event_type is not null
    group by node_name
    having count(*) >= 3
    order by p50 desc
    limit 50
    """
)

with engine.connect() as conn:
    df_slow = pd.read_sql(sql_slowest, conn, params={'from_ts': lookback_from, 'path_substr': PLAYBOOK_PATH})

fig = px.bar(df_slow, x='node_name', y='p50', title='Slowest steps by P50 duration (s)')
fig.show()

#%% md
## Drill-down: pick a run to analyze
#
# Set `EXECUTION_ID` to one of the recent runs to render a timeline and error details.

#%%
EXECUTION_ID = int(df_overview.iloc[0]['execution_id']) if len(df_overview) else None
EXECUTION_ID

#%%
# Timeline data for a single execution
if EXECUTION_ID is not None:
    sql_timeline = text(
        """
        select event_id, created_at, node_name, node_type, status, duration, error
        from noetl.event
        where execution_id = :exec_id
        order by created_at asc
        """
    )
    with engine.connect() as conn:
        df_tl = pd.read_sql(sql_timeline, conn, params={'exec_id': EXECUTION_ID})

    # Compute end time from created_at + duration (seconds)
    df_tl['start'] = pd.to_datetime(df_tl['created_at'])
    df_tl['end'] = df_tl['start'] + pd.to_timedelta(df_tl['duration'].fillna(0), unit='s')
    df_tl['label'] = df_tl['node_name'].fillna(df_tl['node_type'])
    display(df_tl.head(10))
else:
    df_tl = pd.DataFrame()
    print('No executions found in the selected window.')

#%%
# Plot timeline (Gantt-like)
if not df_tl.empty:
    fig = px.timeline(
        df_tl,
        x_start='start',
        x_end='end',
        y='label',
        color='status',
        hover_data=['event_id', 'node_type', 'duration', 'error']
    )
    fig.update_yaxes(autorange='reversed')
    fig.update_layout(title=f'Execution timeline — {EXECUTION_ID}')
    fig.show()
else:
    print('No timeline data to plot.')

#%%
# Error details for the chosen run (latest error per step)
if EXECUTION_ID is not None:
    sql_err = text(
        """
        with ranked as (
          select node_name, error, created_at,
                 row_number() over(partition by node_name order by created_at desc) as rn
          from noetl.event
          where execution_id = :exec_id and status = 'error' and error is not null
        )
        select node_name, error, created_at
        from ranked
        where rn = 1
        order by created_at desc
        """
    )
    with engine.connect() as conn:
        df_err = pd.read_sql(sql_err, conn, params={'exec_id': EXECUTION_ID})
    display(df_err)
else:
    print('No execution selected.')

#%% md
## Notes
#
# - This reads raw `noetl.event` rows; future improvement: materialized views for faster rollups.
# - To analyze different playbooks, change `PLAYBOOK_PATH` to another path or broader pattern.
# - Inside Kind JupyterLab (analytics namespace), use the in-cluster DNS host:
#   `postgres.postgres.svc.cluster.local:5432` (the default `pg_local.json` points there).
# - From host, prefer `localhost:54321` (Kind NodePort mapped in `ci/kind/config.yaml`).
