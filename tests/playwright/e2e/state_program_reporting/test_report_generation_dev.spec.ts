import { test, expect, type APIRequestContext } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';
import { readFile } from 'fs/promises';

dotenv.config({ quiet: true });
// When running via `tests/playwright/package.json`, the cwd is `tests/playwright/`.
// Fall back to the repo root `.env` so local runs and CI behave the same.
if (!process.env.STATE_REPORT_PG_USER) {
    dotenv.config({ path: path.resolve(process.cwd(), '../..', '.env'), quiet: true });
}
const CREDENTIAL_NAME = 'gcs_bhs_state_program_hmac';
const PLAYBOOK_NAME = 'state_report_generation_dev';
const NOETL_HOST_RAW = process.env.NOETL_HOST ?? '127.0.0.1';
const NOETL_HOST = NOETL_HOST_RAW === 'localhost' ? '127.0.0.1' : NOETL_HOST_RAW;
const NOETL_PORT = process.env.NOETL_PORT ?? '8099';
const API_BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const CATALOG_URL = `${BASE_URL}/catalog`;
const CREDENTIALS_URL = `${BASE_URL}/credentials`;
const LOADING_EXECUTIONS_TEXT = 'Loading executions...';
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

const VOLATILE_KEYS = new Set<string>(['fetched_at', 'headers', 'elapsed', 'url']);

function sanitizeSample(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map((v) => sanitizeSample(v));
    }

    if (value && typeof value === 'object') {
        const input = value as Record<string, unknown>;
        const output: Record<string, unknown> = {};
        for (const [key, child] of Object.entries(input)) {
            if (VOLATILE_KEYS.has(key)) continue;
            output[key] = sanitizeSample(child);
        }
        return output;
    }

    return value;
}

function sortRowsByPatientId(value: unknown): unknown {
    if (!Array.isArray(value)) return value;

    const rows = [...value];
    rows.sort((a, b) => {
        const aId = (a as { pcc_patient_id?: unknown } | null)?.pcc_patient_id;
        const bId = (b as { pcc_patient_id?: unknown } | null)?.pcc_patient_id;
        if (typeof aId === 'number' && typeof bId === 'number') return aId - bId;
        if (typeof aId === 'string' && typeof bId === 'string') return aId.localeCompare(bId);
        return JSON.stringify(a ?? null).localeCompare(JSON.stringify(b ?? null));
    });
    return rows;
}

function extractPatientIds(value: unknown): number[] {
    if (!Array.isArray(value)) return [];
    const ids = new Set<number>();
    for (const row of value) {
        const id = (row as { pcc_patient_id?: unknown } | null)?.pcc_patient_id;
        if (typeof id === 'number' && Number.isFinite(id)) ids.add(id);
        if (typeof id === 'string' && id.trim() !== '' && Number.isFinite(Number(id))) ids.add(Number(id));
    }
    return [...ids].sort((a, b) => a - b);
}

async function readJsonFile<T>(filePath: string): Promise<T> {
    const text = await readFile(filePath, 'utf-8');
    return JSON.parse(text) as T;
}

function requireEnv(name: string): string {
    const value = process.env[name];
    if (!value) {
        throw new Error(`Missing env var ${name}`);
    }
    return value;
}

function envWithFallback(primaryName: string, fallbackName: string): string {
    return process.env[primaryName] ?? requireEnv(fallbackName);
}

function buildStateReportConnectionString(): string {
    const user = requireEnv('STATE_REPORT_PG_USER');
    const password = requireEnv('STATE_REPORT_PG_PASSWORD');
    const host = envWithFallback('STATE_REPORT_PG_HOST_FROM_NOETL', 'STATE_REPORT_PG_HOST');
    const port = envWithFallback('STATE_REPORT_PG_PORT_FROM_NOETL', 'STATE_REPORT_PG_PORT');
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

async function collectPublicTableStats(
    request: APIRequestContext,
    connectionString: string,
    table: string,
    summary: Record<string, number>
): Promise<number> {
    await test.step(`Table exists: public.${table}`, async () => {
        const result = (await postgresExecute(request, {
            query: `SELECT to_regclass(format('public.%I', '${table}')) AS regclass`,
            connection_string: connectionString,
        })) as Array<{ regclass: string | null }>;
        expect(result[0]?.regclass).not.toBeNull();
    });

    await test.step(`Table stats: public.${table}`, async () => {
        const countResult = (await postgresExecute(request, {
            query: `SELECT COUNT(*)::bigint AS row_count FROM public.${table}`,
            connection_string: connectionString,
        })) as Array<{ row_count: number | string }>;

        const rowCount = Number(countResult[0]?.row_count ?? 0);
        summary[table] = rowCount;

        const samplesDir = path.resolve(__dirname, 'report_generation_sample');
        const expectedSamplePath = path.join(samplesDir, `${table}.sample.json`);

        let expectedSampleRows: unknown;
        try {
            expectedSampleRows = await readJsonFile<unknown>(expectedSamplePath);
        } catch (e) {
            // If there is no sample file (e.g., table expected empty), do not compare row content.
            return;
        }

        const patientIds = extractPatientIds(expectedSampleRows);
        if (patientIds.length === 0) {
            // If sample doesn't contain pcc_patient_id (or empty), do not try strict row-content compare.
            return;
        }

        // Compare the same logical rows by primary business key.
        const idListSql = patientIds.join(',');
        const actualSampleRows = (await postgresExecute(request, {
            query: `SELECT * FROM public.${table} WHERE pcc_patient_id IN (${idListSql}) ORDER BY pcc_patient_id ASC`,
            connection_string: connectionString,
        })) as unknown;

        const sanitizedExpected = sortRowsByPatientId(sanitizeSample(expectedSampleRows));
        const sanitizedActual = sortRowsByPatientId(sanitizeSample(actualSampleRows));

        expect(sanitizedActual, `public.${table} sample matches ${path.basename(expectedSamplePath)}`).toEqual(sanitizedExpected);
    });

    return summary[table] ?? 0;
}


test('state report generation: tables have data', async ({ page, request }) => {
    await test.step('Navigate: open Credentials', async () => {
        await page.goto(CREDENTIALS_URL);
        await expect(page).toHaveTitle('NoETL Dashboard');
    });
    await test.step(`Type "${CREDENTIAL_NAME}" into search input`, async () => {
        const searchInput = page.locator("//input[@placeholder='Search credentials by name, type, description, or tags...']");
        await searchInput.fill(CREDENTIAL_NAME);
        await page.waitForTimeout(1000);
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
        await page.waitForTimeout(1000);
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
        await loader.waitFor({ state: 'detached' });
    });

    await test.step('Wait for completion, then reload', async () => {
        await page.waitForTimeout(30000);
        await page.reload();
        await expect(page).toHaveTitle('NoETL Dashboard');
    });

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

        const summary: Record<string, number> = {};

        for (const table of tablesToCheck) {
            await collectPublicTableStats(request, connectionString, table, summary);
        }

        const samplesDir = path.resolve(__dirname, 'report_generation_sample');
        const expectedSummaryPath = path.join(samplesDir, 'summary.json');
        let expectedCounts: Record<string, number> = {};
        try {
            const expectedSummary = await readJsonFile<{ counts?: Record<string, number> }>(expectedSummaryPath);
            expectedCounts = expectedSummary.counts ?? {};
        } catch (e) {
            // Local/CI runs may not have golden samples checked in.
            // When missing, only validate minimum row-count expectations below.
            expectedCounts = {};
        }

        if (Object.keys(expectedCounts).length > 0) {
            // Compare recorded counts vs fresh counts.
            for (const table of tablesToCheck) {
                const expected = expectedCounts[table];
                if (typeof expected === 'number') {
                    expect(summary[table], `public.${table} row_count`).toBe(expected);
                }
            }
        }

        // Now that we captured real contents, validate row-count expectations.
        const expectedMinRows: Record<(typeof tablesToCheck)[number], number> = {
            patient_adt_records: 1,
            patient_assessments: 1,
            patient_conditions: 1,
            patient_demographics: 1,
            patient_ids_work: 0,
            patient_medications: 1,
        };

        for (const table of tablesToCheck) {
            const rowCount = summary[table] ?? 0;
            expect(rowCount, `public.${table} row_count`).toBeGreaterThanOrEqual(expectedMinRows[table]);
        }
    });


});