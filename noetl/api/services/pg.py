import csv
import json
from psycopg.rows import dict_row
from noetl.connectors.hub import ConnectorHub
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

async def export_csv(query, file_path, context: ConnectorHub, headers=True):
    if not context.postgres:
        logger.error("Postgres connection is not initialized.")
        raise RuntimeError("Database not initialized.")

    async with context.postgres.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query)
            rows = await cursor.fetchall()
            if not rows:
                logger.warning("No data fetched.")
                return {"status": "no data", "file_path": file_path}

            columns = rows[0].keys()

            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(
                    csvfile, fieldnames=columns,
                    quoting=csv.QUOTE_ALL, doublequote=True
                )
                if headers:
                    writer.writeheader()
                for row in rows:
                    csv_row = {}
                    for col, val in row.items():
                        if isinstance(val, (dict, list)):
                            csv_row[col] = json.dumps(val, ensure_ascii=False)
                        else:
                            csv_row[col] = val
                    writer.writerow(csv_row)
    logger.info(f"CSV export file: {file_path}",  extra={"headers":headers})
    return {"status": "success", "file_path": file_path}


async def import_csv(table_name, file_path, context: ConnectorHub, schema_name='public', headers=True, column_names=None):
    if not context.postgres:
        logger.error("Postgres connection is not initialized.")
        raise RuntimeError("Database not initialized.")

    async with context.postgres.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
            """, (schema_name, table_name))

            schema = await cursor.fetchall()
            schema_types = {col['column_name']: col['data_type'] for col in schema}

            if not headers and not column_names:
                raise ValueError("Column names must be provided if CSV has no headers.")

            with open(file_path, newline='', encoding='utf-8') as csvfile:
                if headers:
                    reader = csv.DictReader(
                        csvfile,
                        quoting=csv.QUOTE_ALL, doublequote=True
                    )
                    columns = reader.fieldnames
                else:
                    reader = csv.reader(
                        csvfile,
                        quoting=csv.QUOTE_ALL, doublequote=True
                    )
                    columns = column_names

                placeholders = ', '.join(['%s'] * len(columns))
                col_names = ', '.join(columns)

                insert_stmt = f"""
                    INSERT INTO {schema_name}.{table_name} ({col_names})
                    VALUES ({placeholders})
                """

                if headers:
                    for row in reader:
                        values = []
                        for col in columns:
                            val = row[col]
                            data_type = schema_types.get(col)

                            if data_type in ('json', 'jsonb'):
                                parsed_val = json.loads(val) if val else None
                                val = json.dumps(parsed_val, ensure_ascii=False) if parsed_val else None
                            values.append(val)
                        await cursor.execute(insert_stmt, values)
                else:
                    for row in reader:
                        if len(row) != len(columns):
                            raise ValueError(f"Row length mismatch: {row}")
                        values = []
                        for col, val in zip(columns, row):
                            data_type = schema_types.get(col)

                            if data_type in ('json', 'jsonb'):
                                parsed_val = json.loads(val) if val else None
                                val = json.dumps(parsed_val, ensure_ascii=False) if parsed_val else None
                            values.append(val)
                        await cursor.execute(insert_stmt, values)

        await conn.commit()

    logger.info(f"CSV records imported into {schema_name}.{table_name}")
    return {"status": "success", "table": f"{schema_name}.{table_name}", "file_path": file_path}
