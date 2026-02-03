import { test, expect, type APIRequestContext } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

dotenv.config();
// When running via `tests/playwright/package.json`, the cwd is `tests/playwright/`.
// Fall back to the repo root `.env` so local runs and CI behave the same.
if (!process.env.STATE_REPORT_PG_USER) {
    dotenv.config({ path: path.resolve(process.cwd(), '../..', '.env') });
}
const CREDENTIAL_NAME = 'gcs_bhs_state_program_hmac';

const PLAYBOOK_NAME = 'state_report_create_tables';

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';
const NOETL_HOST_RAW = process.env.NOETL_HOST ?? '127.0.0.1';
const NOETL_HOST = NOETL_HOST_RAW === 'localhost' ? '127.0.0.1' : NOETL_HOST_RAW;
const NOETL_PORT = process.env.NOETL_PORT ?? '8099';
const API_BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const CATALOG_URL = `${BASE_URL}/catalog`;
const CREDENTIALS_URL = `${BASE_URL}/credentials`;

const STATE_REPORT_PG_USER = process.env.STATE_REPORT_PG_USER;
const STATE_REPORT_PG_PASSWORD = process.env.STATE_REPORT_PG_PASSWORD;
const STATE_REPORT_PG_DB = process.env.STATE_REPORT_PG_DB;

const STATE_REPORT_PG_HOST_FROM_NOETL =
    process.env.STATE_REPORT_PG_HOST_FROM_NOETL ?? process.env.STATE_REPORT_PG_HOST;
const STATE_REPORT_PG_PORT_FROM_NOETL =
    process.env.STATE_REPORT_PG_PORT_FROM_NOETL ?? process.env.STATE_REPORT_PG_PORT;

const STATE_REPORT_EXPECT_EMPTY = (process.env.STATE_REPORT_EXPECT_EMPTY ?? 'true') === 'true';

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
    await test.step(`Table exists + empty: public.${table}`, async () => {
        const existsResult = (await postgresExecute(request, {
            query: `SELECT to_regclass(format('public.%I', '${table}')) AS regclass`,
            connection_string: connectionString,
        })) as Array<{ regclass: string | null }>;
        expect(existsResult[0]?.regclass).not.toBeNull();

        const countResult = (await postgresExecute(request, {
            query: `SELECT COUNT(*)::bigint AS row_count FROM public.${table}`,
            connection_string: connectionString,
        })) as Array<{ row_count: number | string }>;
        const rowCount = Number(countResult[0]?.row_count ?? 0);

        const sampleRows = (await postgresExecute(request, {
            query: `SELECT * FROM public.${table} LIMIT 5`,
            connection_string: connectionString,
        })) as unknown;

        test.info().attach(`db.${table}.count.json`, {
            contentType: 'application/json',
            body: Buffer.from(JSON.stringify({ table: `public.${table}`, row_count: rowCount }, null, 2)),
        });
        test.info().attach(`db.${table}.sample.json`, {
            contentType: 'application/json',
            body: Buffer.from(JSON.stringify(sampleRows, null, 2)),
        });

        expect(Array.isArray(sampleRows), `public.${table} sample should be an array`).toBeTruthy();

        if (STATE_REPORT_EXPECT_EMPTY) {
            expect(rowCount, `public.${table} row_count`).toBe(0);
            expect((sampleRows as unknown[]).length, `public.${table} sample length`).toBe(0);
        }
    });
}


test('should open catalog page', async ({ page, request }) => {
    test.setTimeout(120_000);

    await test.step('Navigate: open Credentials', async () => {
        await page.goto(CREDENTIALS_URL);
        await expect(page).toHaveTitle('NoETL Dashboard');
    });
    await test.step(`Type "${CREDENTIAL_NAME}" into search input`, async () => {
        const searchInput = page.locator("//input[@placeholder='Search credentials by name, type, description, or tags...']");
        await searchInput.fill(CREDENTIAL_NAME);
    });
    await test.step('Check search results', async () => {
        const credentialRow = page.locator(
            `(//*[text()='${CREDENTIAL_NAME}'])[1]`
        );
        await expect(credentialRow).toBeVisible();
    });

    await test.step('Navigate: open Catalog', async () => {
        await page.goto(CATALOG_URL);
        await expect(page).toHaveTitle('NoETL Dashboard');
    });

    await test.step(`Type "${PLAYBOOK_NAME}" into search input`, async () => {
        const searchInput = page.locator("//input[@placeholder='Search playbooks...']");
        await searchInput.fill(PLAYBOOK_NAME);
    });
    await test.step('Check search results', async () => {
        const executeButton = page.locator(
            `(//*[text()='${PLAYBOOK_NAME}']/following::button[normalize-space()='Execute'])[1]`
        );
        await expect(executeButton).toBeVisible();
        await test.step(`Execute ${PLAYBOOK_NAME} from Catalog`, async () => {
            await executeButton.click();
            await expect(page).toHaveURL(/\/execution/);
        });
    });

    await test.step('Wait: loader finishes (if present)', async () => {
        const loader = page.locator(`//*[text()='${LOADING_EXECUTIONS_TEXT}']`);
        await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
        await loader.waitFor({ state: 'detached', timeout: 60_000 }).catch(() => { });
    });

    await test.step('Wait: tables created in Postgres', async () => {
        expect(STATE_REPORT_PG_USER).toBeTruthy();
        expect(STATE_REPORT_PG_PASSWORD).toBeTruthy();
        expect(STATE_REPORT_PG_DB).toBeTruthy();
        expect(STATE_REPORT_PG_HOST_FROM_NOETL).toBeTruthy();
        expect(STATE_REPORT_PG_PORT_FROM_NOETL).toBeTruthy();

        const connectionString = buildStateReportConnectionString();

        const tablesToCheck = [
            'patient_adt_records',
            'patient_assessments',
            'patient_conditions',
            'patient_demographics',
            'patient_ids_work',
            'patient_medications',
        ] as const;

        await expect
            .poll(
                async () => {
                    try {
                        for (const table of tablesToCheck) {
                            const existsResult = (await postgresExecute(request, {
                                query: `SELECT to_regclass(format('public.%I', '${table}')) AS regclass`,
                                connection_string: connectionString,
                            })) as Array<{ regclass: string | null }>;
                            if (!existsResult[0]?.regclass) return false;
                        }
                        return true;
                    } catch {
                        return false;
                    }
                },
                { timeout: 90_000, intervals: [1_000, 2_000, 5_000] }
            )
            .toBe(true);
    });

    await test.step('Validate: state report Postgres table exists and is empty', async () => {
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

        const summary: Record<string, number> = {};

        for (const table of tablesToCheck) {
            await assertPublicTableExistsAndEmpty(request, connectionString, table);

            const countResult = (await postgresExecute(request, {
                query: `SELECT COUNT(*)::bigint AS row_count FROM public.${table}`,
                connection_string: connectionString,
            })) as Array<{ row_count: number | string }>;
            summary[table] = Number(countResult[0]?.row_count ?? 0);
        }

        test.info().attach('db.state_report.create_tables.summary.json', {
            contentType: 'application/json',
            body: Buffer.from(JSON.stringify({ expect_empty: STATE_REPORT_EXPECT_EMPTY, counts: summary }, null, 2)),
        });
    });


});