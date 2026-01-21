import { test, expect, type APIRequestContext } from '@playwright/test';
import * as dotenv from 'dotenv';

dotenv.config();
const NOETL_HOST_RAW = process.env.NOETL_HOST ?? '127.0.0.1';
const NOETL_HOST = NOETL_HOST_RAW === 'localhost' ? '127.0.0.1' : NOETL_HOST_RAW;
const NOETL_PORT = process.env.NOETL_PORT ?? '8099';
const API_BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const STATE_REPORT_PG_USER = process.env.STATE_REPORT_PG_USER;
const STATE_REPORT_PG_PASSWORD = process.env.STATE_REPORT_PG_PASSWORD;
const STATE_REPORT_PG_DB = process.env.STATE_REPORT_PG_DB;

const STATE_REPORT_PG_HOST_FROM_NOETL =
    process.env.STATE_REPORT_PG_HOST_FROM_NOETL ?? process.env.STATE_REPORT_PG_HOST;
const STATE_REPORT_PG_PORT_FROM_NOETL =
    process.env.STATE_REPORT_PG_PORT_FROM_NOETL ?? process.env.STATE_REPORT_PG_PORT;

type PostgresExecuteResponse = {
    status?: string;
    result?: unknown;
    error?: string;
    message?: string;
};

function requireEnv(name: string): string {
    const value = process.env[name];
    if (!value) {
        throw new Error(`Missing env var ${name}`);
    }
    return value;
}

function buildStateReportConnectionString(): string {
    const user = requireEnv('STATE_REPORT_PG_USER');
    const password = requireEnv('STATE_REPORT_PG_PASSWORD');
    const host = requireEnv('STATE_REPORT_PG_HOST_FROM_NOETL');
    const port = requireEnv('STATE_REPORT_PG_PORT_FROM_NOETL');
    const db = requireEnv('STATE_REPORT_PG_DB');
    return `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(password)}@${host}:${port}/${encodeURIComponent(db)}`;
}

async function postgresExecute(
    request: APIRequestContext,
    args: { query: string; connection_string?: string; database?: string }
): Promise<unknown> {
    const response = await request.post(`${API_BASE_URL}/api/postgres/execute`, {
        data: args,
    });
    await expect(response).toBeOK();

    const payload = (await response.json()) as PostgresExecuteResponse;
    if (payload.status !== 'ok') {
        throw new Error(`postgres execute failed: status=${payload.status ?? 'unknown'} error=${payload.error ?? payload.message ?? 'unknown'}`);
    }
    return payload.result;
}

async function assertPublicTableExistsAndEmpty(
    request: APIRequestContext,
    connectionString: string,
    table: string
): Promise<void> {
    await test.step(`Table exists: public.${table}`, async () => {
        const result = (await postgresExecute(request, {
            query: `SELECT to_regclass(format('public.%I', '${table}')) AS regclass`,
            connection_string: connectionString,
        })) as Array<{ regclass: string | null }>;
        expect(result[0]?.regclass).not.toBeNull();
    });

    await test.step(`Table empty: public.${table}`, async () => {
        const result = (await postgresExecute(request, {
            query: `SELECT COUNT(*)::bigint AS row_count FROM public.${table}`,
            connection_string: connectionString,
        })) as Array<{ row_count: number | string }>;
        expect(result[0]?.row_count).toBe(0);
    });
}

async function assertPublicTableHasRows(
    request: APIRequestContext,
    connectionString: string,
    table: string
): Promise<void> {
    await test.step(`Table exists: public.${table}`, async () => {
        const result = (await postgresExecute(request, {
            query: `SELECT to_regclass(format('public.%I', '${table}')) AS regclass`,
            connection_string: connectionString,
        })) as Array<{ regclass: string | null }>;
        expect(result[0]?.regclass).not.toBeNull();
    });

    await test.step(`Table has rows: public.${table}`, async () => {
        const countResult = (await postgresExecute(request, {
            query: `SELECT COUNT(*)::bigint AS row_count FROM public.${table}`,
            connection_string: connectionString,
        })) as Array<{ row_count: number | string }>;

        const rowCount = Number(countResult[0]?.row_count ?? 0);
        test.info().attach(`db.${table}.count.json`, {
            contentType: 'application/json',
            body: Buffer.from(JSON.stringify({ table: `public.${table}`, row_count: rowCount }, null, 2)),
        });

        const sampleRows = (await postgresExecute(request, {
            query: `SELECT * FROM public.${table} LIMIT 5`,
            connection_string: connectionString,
        })) as unknown;
        test.info().attach(`db.${table}.sample.json`, {
            contentType: 'application/json',
            body: Buffer.from(JSON.stringify(sampleRows, null, 2)),
        });

        expect(rowCount).toBeGreaterThan(0);
    });
}


test('state report generation: tables have data', async ({ request }) => {

    await test.step('Validate: state report Postgres tables exist and have data', async () => {
        expect(STATE_REPORT_PG_USER).toBeTruthy();
        expect(STATE_REPORT_PG_PASSWORD).toBeTruthy();
        expect(STATE_REPORT_PG_DB).toBeTruthy();
        expect(STATE_REPORT_PG_HOST_FROM_NOETL).toBeTruthy();
        expect(STATE_REPORT_PG_PORT_FROM_NOETL).toBeTruthy();

        const connectionString = buildStateReportConnectionString();

        await test.step('Connect as state report user', async () => {
            const result = (await postgresExecute(request, {
                query: 'SELECT current_user AS user, current_database() AS db',
                connection_string: connectionString,
            })) as Array<{ user: string; db: string }>;
            expect(result[0]?.user).toBe(STATE_REPORT_PG_USER);
            expect(result[0]?.db).toBe(STATE_REPORT_PG_DB);
        });

        const tablesToCheck = [
            'patient_adt_records',
            'patient_assessments',
            'patient_conditions',
            'patient_demographics',
            'patient_ids_work',
            'patient_medications',
        ] as const;

        for (const table of tablesToCheck) {
            await assertPublicTableHasRows(request, connectionString, table);
        }
    });


});