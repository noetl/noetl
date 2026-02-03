// E2E: State program Excel report regression.
//
// Goal:
// - Download a baseline (etalon) Excel report from GCS.
// - Trigger NoETL to generate a fresh report, download it from GCS.
// - Validate the fresh report has all baseline sheets (and non-empty data), then compare parsed samples.
//
// Inputs (env):
// - STATE_REPORT_EXCEL_BASELINE_GCS_URI (preferred) or STATE_REPORT_EXCEL_GCS_URI (legacy): baseline gs:// URI.
// - NOETL_HOST/NOETL_PORT: NoETL API base address.
// - Optional: STATE_REPORT_EXCEL_FRESH_GCS_URI to skip generation and compare two existing files.
// - Optional: STATE_REPORT_EXCEL_FACILITY_NAME, STATE_REPORT_EXCEL_GENERATE_PLAYBOOK_PATH, STATE_REPORT_EXCEL_PG_AUTH,
//   STATE_REPORT_EXCEL_GCS_BUCKET for generation tuning.
// - Optional: STATE_REPORT_EXCEL_IGNORE_COLUMNS to null out volatile columns in the comparison.
import { test, expect, type APIRequestContext } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';
import { writeFile, readFile, mkdir } from 'fs/promises';
import { existsSync, statSync } from 'fs';
import { Storage } from '@google-cloud/storage';
import ExcelJS from 'exceljs';

// Load env for local runs and CI.
dotenv.config({ override: true });
// When running via `tests/playwright/package.json`, the cwd is `tests/playwright/`.
// Fall back to the repo root `.env` so local runs and CI behave the same.
if (!process.env.STATE_REPORT_PG_USER) {
    dotenv.config({ path: path.resolve(process.cwd(), '../..', '.env'), override: true });
}

// NoETL API address.
const NOETL_HOST_RAW = process.env.NOETL_HOST ?? '127.0.0.1';
const NOETL_HOST = NOETL_HOST_RAW === 'localhost' ? '127.0.0.1' : NOETL_HOST_RAW;
const NOETL_PORT = process.env.NOETL_PORT ?? '8099';
const API_BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

// -----------------------------
// Types (API + Excel sampling)
// -----------------------------
// Keep these types local to the test file:
// - They document the expected JSON shapes.
// - They help TypeScript catch drift when the API output changes.

// Response from POST /api/execute.
type ExecuteResponse = {
    execution_id: string;
    status: string;
    commands_generated: number;
};

// Response from GET /api/executions/{id}/status.
type ExecutionStatusResponse = {
    execution_id: string;
    current_step: string | null;
    completed_steps: string[];
    failed: boolean;
    completed: boolean;
    variables: Record<string, unknown>;
};

// A deterministic summary of one worksheet.
// We don’t compare binary XLSX bytes; we compare a stable JSON sample instead.
type ExcelSheetSample = {
    columns: string[];
    row_count: number;
    sample_rows: Array<Record<string, unknown>>;
};

// A deterministic summary of the whole workbook.
type ExcelWorkbookSample = {
    sheet_names: string[];
    sheets: Record<string, ExcelSheetSample>;
};

// -----------------------------
// Debug snapshots (optional)
// -----------------------------
// Optional: persist a JSON snapshot of the *baseline* sample for debugging.
const EXCEL_SAMPLE_DIR = path.resolve(__dirname, 'report_excel_sample');
const EXCEL_SAMPLE_PATH = path.join(EXCEL_SAMPLE_DIR, 'state_report_excel.sample.json');

// When true, writes the parsed baseline sample JSON to EXCEL_SAMPLE_PATH.
const UPDATE_EXCEL_SAMPLE = (process.env.UPDATE_STATE_REPORT_EXCEL_SAMPLE ?? 'false') === 'true';

// -----------------------------
// Excel comparison normalization
// -----------------------------

/**
 * Columns that are volatile between runs (timestamps, generated markers) can be nulled out
 * to keep the baseline-vs-fresh comparison stable.
 */
function parseIgnoredColumnsFromEnv(): Set<string> {
    const raw = process.env.STATE_REPORT_EXCEL_IGNORE_COLUMNS;
    const defaults = [
        'parsed_at',
        'fetched_at',
        'created_at',
        'updated_at',
        'generated_at',
        'report_generated_at',
    ];

    const items = (raw && raw.trim() !== '' ? raw.split(',') : defaults)
        .map((s) => s.trim().toLowerCase())
        .filter((s) => s.length > 0);

    return new Set(items);
}

const IGNORED_COLUMNS = parseIgnoredColumnsFromEnv();

// Normalize ExcelJS cell values into JSON-friendly primitives.
function normalizeCellValue(value: unknown): unknown {
    if (value instanceof Date) return value.toISOString();
    if (typeof value === 'number' && Number.isNaN(value)) return null;
    return value;
}

/**
 * Legacy hook: a fixed expected sheet list.
 * Current default behavior is stricter: fresh must match baseline's sheet set.
 */
function parseExpectedSheetsFromEnv(): string[] {
    const raw = process.env.STATE_REPORT_EXCEL_EXPECTED_SHEETS;
    const defaults = ['Demographics', 'Conditions', 'Medications', 'ADT Records', 'Assessments'];

    const items = (raw && raw.trim() !== '' ? raw.split(',') : defaults)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);

    return items;
}

// Validates required sheets exist and are non-empty.
function assertWorkbookHasExpectedSheets(sample: ExcelWorkbookSample, expectedSheets: string[], label: string): void {
    const actualByLower = new Map(sample.sheet_names.map((name) => [name.toLowerCase(), name] as const));

    for (const expected of expectedSheets) {
        const actualName = actualByLower.get(expected.toLowerCase());
        expect(
            actualName,
            `${label}: missing expected sheet "${expected}". Actual sheets: ${sample.sheet_names.join(', ')}`
        ).toBeTruthy();

        const sheetSample = sample.sheets[actualName ?? expected];
        expect(sheetSample, `${label}: missing sheet sample for "${expected}"`).toBeTruthy();
        expect(sheetSample.columns.length, `${label}: "${expected}" columns`).toBeGreaterThan(0);
        expect(sheetSample.row_count, `${label}: "${expected}" row_count`).toBeGreaterThan(0);
    }
}

async function parseExcelToSample(excelBytes: Buffer, opts?: { maxRowsPerSheet?: number }): Promise<ExcelWorkbookSample> {
    // Convert an XLSX into a deterministic JSON “sample”.
    // The sample intentionally captures:
    // - sheet_names
    // - header columns
    // - row_count
    // - up to N sample rows
    // This keeps diffs readable compared to raw XLSX binary diffs.
    const maxRowsPerSheet = opts?.maxRowsPerSheet ?? 20;

    const workbook = new ExcelJS.Workbook();
    type XlsxLoadArg = Parameters<InstanceType<typeof ExcelJS.Workbook>['xlsx']['load']>[0];
    await workbook.xlsx.load(excelBytes as unknown as XlsxLoadArg);

    const sheetNames = workbook.worksheets.map((ws) => ws.name);
    const sheets: Record<string, ExcelSheetSample> = {};

    for (const worksheet of workbook.worksheets) {
        // Identify a header row by scanning the first few rows for the first non-empty row.
        const columns: string[] = [];

        const scanRows = Math.min(worksheet.actualRowCount ?? 50, 50);
        let headerRowIndex: number | null = null;
        let maxCol = 0;

        for (let r = 1; r <= scanRows; r++) {
            const row = worksheet.getRow(r);
            let hasValue = false;
            row.eachCell({ includeEmpty: false }, (cell) => {
                const v = (cell as unknown as { value?: unknown }).value;
                if (v !== null && v !== undefined && v !== '') {
                    hasValue = true;
                    const colNum = (cell as unknown as { col?: number }).col;
                    if (typeof colNum === 'number' && colNum > maxCol) maxCol = colNum;
                }
            });
            if (hasValue) {
                headerRowIndex = r;
                break;
            }
        }

        if (headerRowIndex !== null && maxCol > 0) {
            const headerRow = worksheet.getRow(headerRowIndex);
            for (let col = 1; col <= maxCol; col++) {
                const cellValue = headerRow.getCell(col).value;
                const header = (typeof cellValue === 'string' ? cellValue : String(cellValue ?? '')).trim();
                columns.push(header || `col_${col}`);
            }
        }

        // Approximate data row count (rows below the header row).
        const rowCount =
            headerRowIndex === null
                ? 0
                : Math.max((worksheet.actualRowCount ?? headerRowIndex) - headerRowIndex, 0);
        const sampleRows: Array<Record<string, unknown>> = [];

        if (headerRowIndex !== null && columns.length > 0) {
            const firstDataRow = headerRowIndex + 1;
            const lastRow = worksheet.actualRowCount ?? headerRowIndex;
            const sampleLast = Math.min(lastRow, firstDataRow + maxRowsPerSheet - 1);
            for (let r = firstDataRow; r <= sampleLast; r++) {
                const row = worksheet.getRow(r);
                const obj: Record<string, unknown> = {};
                for (let c = 1; c <= columns.length; c++) {
                    const key = columns[c - 1];
                    const cell = row.getCell(c);
                    const raw = (cell as unknown as { value?: unknown }).value;

                    if (IGNORED_COLUMNS.has(key.trim().toLowerCase())) {
                        obj[key] = null;
                    } else {
                        obj[key] = normalizeCellValue(raw);
                    }
                }
                sampleRows.push(obj);
            }
        }

        sheets[worksheet.name] = {
            columns,
            row_count: rowCount,
            sample_rows: sampleRows,
        };
    }

    return {
        sheet_names: sheetNames,
        sheets,
    };
}

async function writeJsonPretty(filePath: string, value: unknown): Promise<void> {
    // Helper for debug snapshots.
    await mkdir(path.dirname(filePath), { recursive: true });
    await writeFile(filePath, JSON.stringify(value, null, 2) + '\n', 'utf-8');
}

async function readJson<T>(filePath: string): Promise<T> {
    // Generic JSON reader (kept for potential future debug flows).
    const raw = await readFile(filePath, 'utf-8');
    return JSON.parse(raw) as T;
}

// -----------------------------
// GCS access helpers
// -----------------------------
// The test downloads Excel artifacts directly from GCS using @google-cloud/storage.
// Auth is handled via Application Default Credentials (ADC) or GOOGLE_APPLICATION_CREDENTIALS.

function normalizeGoogleApplicationCredentials(): void {
    // Some local environments have a stale GOOGLE_APPLICATION_CREDENTIALS pointing to a missing file.
    // If so, delete it so the Google SDK can fall back to Application Default Credentials.
    const raw = process.env.GOOGLE_APPLICATION_CREDENTIALS;
    if (!raw) return;

    const resolved = path.isAbsolute(raw) ? raw : path.resolve(process.cwd(), raw);
    try {
        if (!existsSync(resolved)) {
            console.warn(
                `[E2E] GOOGLE_APPLICATION_CREDENTIALS points to missing file: ${raw} (resolved: ${resolved}). Falling back to ADC.`
            );
            delete process.env.GOOGLE_APPLICATION_CREDENTIALS;
            return;
        }

        const stats = statSync(resolved);
        if (!stats.isFile()) {
            console.warn(
                `[E2E] GOOGLE_APPLICATION_CREDENTIALS is not a file: ${raw} (resolved: ${resolved}). Falling back to ADC.`
            );
            delete process.env.GOOGLE_APPLICATION_CREDENTIALS;
            return;
        }

        // Prefer absolute path for Google auth library resolution.
        process.env.GOOGLE_APPLICATION_CREDENTIALS = resolved;
    } catch (e) {
        console.warn(
            `[E2E] Failed to validate GOOGLE_APPLICATION_CREDENTIALS=${raw} (resolved: ${resolved}). Falling back to ADC. Error: ${String(
                e
            )}`
        );
        delete process.env.GOOGLE_APPLICATION_CREDENTIALS;
    }
}

function parseGsUri(gsUri: string): { bucket: string; objectPath: string } {
    // Minimal gs:// parser for use with @google-cloud/storage.
    const match = /^gs:\/\/(.+?)\/(.+)$/.exec(gsUri);
    if (!match) {
        throw new Error(`Invalid gs:// URI: ${gsUri}`);
    }
    return { bucket: match[1], objectPath: match[2] };
}

function requireGsUri(raw: string | undefined, name: string): string {
    // Friendly validation for env-provided URIs.
    const value = raw?.trim();
    if (!value) {
        throw new Error(`Missing required env var: ${name}`);
    }
    if (!value.startsWith('gs://')) {
        throw new Error(`${name} must start with gs:// (got: ${value})`);
    }
    return value;
}

async function downloadFromGcs(gsUri: string): Promise<Buffer> {
    // Downloads a GCS object into memory as a Buffer.
    const { bucket, objectPath } = parseGsUri(gsUri);
    try {
        normalizeGoogleApplicationCredentials();
        const storage = new Storage();
        const [contents] = await storage.bucket(bucket).file(objectPath).download();
        return contents;
    } catch (error) {
        throw new Error(
            `Failed to download ${gsUri}. Provide GCS credentials via Application Default Credentials (gcloud auth application-default login) or GOOGLE_APPLICATION_CREDENTIALS. Original error: ${String(
                error
            )}`
        );
    }
}

function validateXlsxSignature(excelBytes: Buffer, label: string): void {
    // Basic guardrails: XLSX is a ZIP with a minimum size.
    expect(excelBytes.length, `${label}: file size`).toBeGreaterThan(1024);
    // XLSX files are ZIP archives, which start with "PK".
    expect(excelBytes.subarray(0, 2).toString('utf-8'), `${label}: signature`).toBe('PK');
}

function findFirstStringByKey(value: unknown, key: string): string | null {
    // Searches nested objects/arrays for the first non-empty string at `key`.
    if (!value) return null;

    if (Array.isArray(value)) {
        for (const item of value) {
            const found = findFirstStringByKey(item, key);
            if (found) return found;
        }
        return null;
    }

    if (typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const direct = record[key];
        if (typeof direct === 'string' && direct.trim() !== '') return direct;

        for (const child of Object.values(record)) {
            const found = findFirstStringByKey(child, key);
            if (found) return found;
        }
    }

    return null;
}

function collectStrings(value: unknown): string[] {
    // Collects all strings from a nested JSON-like structure.
    const out: string[] = [];

    const walk = (v: unknown) => {
        if (v === null || v === undefined) return;
        if (typeof v === 'string') {
            if (v.trim() !== '') out.push(v);
            return;
        }
        if (Array.isArray(v)) {
            for (const item of v) walk(item);
            return;
        }
        if (typeof v === 'object') {
            for (const child of Object.values(v as Record<string, unknown>)) walk(child);
        }
    };

    walk(value);
    return out;
}

function pickBestReportGsUri(opts: {
    variables: Record<string, unknown> | undefined;
    outputFilename: string;
    facilityName: string;
}): { selected: string; candidates: string[] } {
    // Some playbooks put the gs:// URI under a nested step result rather than at variables.gcs_uri.
    // This picks the best-looking XLSX URI from the execution variables.
    const variables = opts.variables ?? {};
    const allStrings = collectStrings(variables);
    const gsUris = allStrings.filter((s) => s.startsWith('gs://'));
    const xlsxUris = gsUris.filter((s) => s.toLowerCase().endsWith('.xlsx'));
    const candidates = (xlsxUris.length > 0 ? xlsxUris : gsUris).filter((s, i, arr) => arr.indexOf(s) === i);

    if (candidates.length === 0) {
        throw new Error('No gs:// URIs found in execution variables; cannot locate generated Excel report.');
    }

    const facilitySlug = opts.facilityName.toLowerCase().replace(/\s+/g, '_');

    const score = (uri: string): number => {
        let s = 0;
        const u = uri.toLowerCase();
        if (u.endsWith('.xlsx')) s += 20;
        if (u.includes('state_report')) s += 10;
        if (u.includes(opts.outputFilename.toLowerCase())) s += 50;
        if (u.includes(facilitySlug)) s += 25;
        return s;
    };

    const ranked = [...candidates].sort((a, b) => score(b) - score(a));
    return { selected: ranked[0], candidates: ranked };
}

// -----------------------------
// NoETL API helpers
// -----------------------------
// These helpers talk to the running NoETL server to generate a report and poll execution status.
// They intentionally keep error messages actionable (wrong host/port, endpoint unreachable, etc.).

async function noetlExecute(request: APIRequestContext, args: { path: string; payload: Record<string, unknown> }): Promise<string> {
    // Trigger a NoETL playbook execution.
    let response;
    try {
        response = await request.post(`${API_BASE_URL}/api/execute`, {
            data: args,
        });
    } catch (error) {
        throw new Error(
            `NoETL API is not reachable at ${API_BASE_URL} (POST /api/execute). Set NOETL_HOST/NOETL_PORT or start/port-forward the NoETL API. Original error: ${String(
                error
            )}`
        );
    }
    await expect(response).toBeOK();

    const payload = (await response.json()) as ExecuteResponse;
    if (!payload.execution_id) {
        throw new Error(`NoETL execute: missing execution_id (status=${payload.status ?? 'unknown'})`);
    }
    return payload.execution_id;
}

async function noetlExecutionStatus(request: APIRequestContext, executionId: string): Promise<ExecutionStatusResponse> {
    // Pollable status endpoint for the execution.
    const url = `${API_BASE_URL}/api/executions/${encodeURIComponent(executionId)}/status`;

    // Port-forward / reverse-proxy can occasionally reset connections.
    // Retry a few times to avoid flaky failures.
    const backoffMs = [250, 500, 1000, 2000];
    let lastError: unknown;

    for (let attempt = 0; attempt <= backoffMs.length; attempt++) {
        try {
            const response = await request.get(url);
            await expect(response).toBeOK();
            return (await response.json()) as ExecutionStatusResponse;
        } catch (error) {
            lastError = error;
            if (attempt === backoffMs.length) break;
            await new Promise((resolve) => setTimeout(resolve, backoffMs[attempt]));
        }
    }

    throw new Error(`NoETL status endpoint failed after retries: ${url}. Last error: ${String(lastError)}`);
}

async function isNoetlReachable(request: APIRequestContext): Promise<boolean> {
    // Reachability check used only to decide whether to skip generation.
    try {
        // Treat any HTTP response as "reachable"; many deployments disable /docs or mount it elsewhere.
        await request.get(`${API_BASE_URL}/`, { timeout: 2000 });
        return true;
    } catch {
        return false;
    }
}

// -----------------------------
// Test scenario
// -----------------------------
// Steps:
// 1) Download baseline XLSX from GCS.
// 2) Generate fresh XLSX via NoETL (unless STATE_REPORT_EXCEL_FRESH_GCS_URI is provided).
// 3) Download fresh XLSX from GCS.
// 4) Parse both into deterministic JSON samples.
// 5) Require: fresh contains all baseline sheets and those sheets are non-empty.
// 6) Compare samples (with volatile columns normalized).
test.describe('State program reporting', () => {
    test('Generates Excel report and downloads it from GCS', async ({ request }, testInfo) => {
        // This test can do real work (NoETL execution + GCS download), so it gets a higher timeout.
        test.setTimeout(5 * 60_000);

        // Use a unique filename so the fresh report doesn't collide with older artifacts in the same bucket.
        const outputFilename = `state_report_e2e_${new Date().toISOString().replace(/[:.]/g, '-')}`;
        const facilityName = process.env.STATE_REPORT_EXCEL_FACILITY_NAME?.trim() || '7 Hills Department';
        const playbookPath =
            process.env.STATE_REPORT_EXCEL_GENERATE_PLAYBOOK_PATH?.trim() || 'bhs/state_report_excel_generation_dev';
        const pgAuthOverride = process.env.STATE_REPORT_EXCEL_PG_AUTH?.trim();
        const gcsBucketOverride = process.env.STATE_REPORT_EXCEL_GCS_BUCKET?.trim();

        let generatedExecutionId: string | null = null;
        let generatedExecutionStatus: ExecutionStatusResponse | null = null;
        let generatedGcsUriCandidates: string[] | null = null;

        // Baseline/etalon Excel is the fixed reference we compare against.
        const baselineGsUri = await test.step('Resolve baseline (etalon) gs:// URI', async () => {
            // Backward-compatible: STATE_REPORT_EXCEL_GCS_URI can be used as baseline.
            const rawBaseline = process.env.STATE_REPORT_EXCEL_BASELINE_GCS_URI;
            const rawLegacy = process.env.STATE_REPORT_EXCEL_GCS_URI;

            if (rawBaseline && rawBaseline.trim() !== '') {
                return requireGsUri(rawBaseline, 'STATE_REPORT_EXCEL_BASELINE_GCS_URI');
            }
            if (rawLegacy && rawLegacy.trim() !== '') {
                return requireGsUri(rawLegacy, 'STATE_REPORT_EXCEL_GCS_URI');
            }

            throw new Error(
                'Missing baseline Excel URI. Set STATE_REPORT_EXCEL_BASELINE_GCS_URI (preferred) or STATE_REPORT_EXCEL_GCS_URI (legacy).'
            );
        });

        // Fresh Excel comes from a new playbook run, unless overridden.
        const freshGsUri = await test.step('Generate a fresh report (or use override URI)', async () => {
            const override = process.env.STATE_REPORT_EXCEL_FRESH_GCS_URI;
            if (override && override.trim() !== '') {
                return requireGsUri(override, 'STATE_REPORT_EXCEL_FRESH_GCS_URI');
            }

            if (!(await isNoetlReachable(request))) {
                test.skip(
                    true,
                    `NoETL API is not reachable at ${API_BASE_URL}. Start NoETL or set NOETL_HOST/NOETL_PORT, or provide STATE_REPORT_EXCEL_FRESH_GCS_URI to compare without generating.`
                );
            }

            // Kick off generation.
            const executionId = await noetlExecute(request, {
                path: playbookPath,
                payload: {
                    output_filename: outputFilename,
                    facility_name: facilityName,
                    ...(pgAuthOverride ? { pg_auth: pgAuthOverride } : {}),
                    ...(gcsBucketOverride ? { gcs_bucket: gcsBucketOverride } : {}),
                },
            });

            generatedExecutionId = executionId;

            // Wait for NoETL to finish before we try to download the artifact.
            const status = await test.step('Wait for execution to complete', async () => {
                await expect
                    .poll(
                        async () => {
                            try {
                                const current = await noetlExecutionStatus(request, executionId);
                                if (current.failed) {
                                    return 'failed';
                                }
                                if (current.completed) {
                                    return 'completed';
                                }
                                return 'running';
                            } catch (e) {
                                // Treat transient network/proxy issues as still running.
                                // If it's persistent, the poll timeout will surface.
                                console.warn(`[E2E] Status poll transient error: ${String(e)}`);
                                return 'running';
                            }
                        },
                        { timeout: 4 * 60_000, intervals: [1000, 1000, 2000, 5000] }
                    )
                    .toBe('completed');

                const current = await noetlExecutionStatus(request, executionId);
                expect(current.failed).toBe(false);
                expect(current.completed).toBe(true);
                return current;
            });

            generatedExecutionStatus = status;

            // Find the GCS URI in the execution variables.
            // Prefer a direct `gcs_uri` key, and fall back to scanning all nested data.
            const directUri = findFirstStringByKey(status.variables, 'gcs_uri');
            if (directUri) {
                const cleaned = requireGsUri(directUri, 'execution.variables.gcs_uri');
                return cleaned;
            }

            const picked = pickBestReportGsUri({
                variables: status.variables,
                outputFilename,
                facilityName,
            });

            generatedGcsUriCandidates = picked.candidates;

            console.log('[E2E] Could not find direct variables.gcs_uri; candidates found:');
            for (const c of picked.candidates.slice(0, 20)) {
                console.log(`  ${c}`);
            }

            return requireGsUri(picked.selected, 'execution.variables (best-candidate gs://)');
        });

        // Download both artifacts as bytes.
        const baselineBytes = await test.step('Download baseline Excel from GCS', async () => {
            return downloadFromGcs(baselineGsUri);
        });

        const freshBytes = await test.step('Download fresh Excel from GCS', async () => {
            return downloadFromGcs(freshGsUri);
        });

        // Guard against downloading HTML error pages or wrong objects.
        await test.step('Validate XLSX signatures', async () => {
            validateXlsxSignature(baselineBytes, 'baseline');
            validateXlsxSignature(freshBytes, 'fresh');
        });

        // Parse baseline first; we will use its sheet set as the strict expectation for the fresh report.
        const baselineSample = await test.step('Parse baseline Excel', async () => {
            const sample = await parseExcelToSample(baselineBytes, { maxRowsPerSheet: 20 });
            const expectedSheets = parseExpectedSheetsFromEnv();

            console.log(`[E2E] Baseline Excel sheets: ${sample.sheet_names.join(', ')}`);
            for (const sheetName of sample.sheet_names) {
                const s = sample.sheets[sheetName];
                console.log(
                    `[E2E] Baseline sheet ${sheetName}: columns=${s?.columns?.length ?? 0} row_count=${s?.row_count ?? 0}`
                );
            }

            await test.step('Validate baseline contains all expected sheets', async () => {
                assertWorkbookHasExpectedSheets(sample, expectedSheets, 'baseline');
            });

            return sample;
        });

        // Parse fresh and validate it contains the same worksheet set as the baseline.
        const freshSample = await test.step('Parse fresh Excel and validate sheet contents', async () => {
            const sample = await parseExcelToSample(freshBytes, { maxRowsPerSheet: 20 });

            expect(sample.sheet_names.length, 'Excel has at least one worksheet').toBeGreaterThan(0);

            console.log(`[E2E] Excel sheets: ${sample.sheet_names.join(', ')}`);
            for (const sheetName of sample.sheet_names) {
                const s = sample.sheets[sheetName];
                console.log(`[E2E] Sheet ${sheetName}: columns=${s?.columns?.length ?? 0} row_count=${s?.row_count ?? 0}`);
            }

            // Strict mode: fresh must contain all baseline sheets and they must be non-empty.
            // Comparison is case-insensitive for sheet names to tolerate Excel naming differences.
            assertWorkbookHasExpectedSheets(sample, baselineSample.sheet_names, 'fresh');

            // Also require that there are no missing baseline sheets (even if extra sheets exist).
            // This is the key requirement: "нужны все листы".
            const baselineSet = new Set(baselineSample.sheet_names.map((s) => s.toLowerCase()));
            const freshSet = new Set(sample.sheet_names.map((s) => s.toLowerCase()));
            for (const baselineSheet of baselineSet) {
                expect(freshSet.has(baselineSheet), `fresh is missing baseline sheet: ${baselineSheet}`).toBe(true);
            }

            return sample;
        });

        // Always write artifacts to disk to make debugging diffs easy.
        await test.step('Save XLSX files to test output', async () => {
            const baselineOutPath = testInfo.outputPath(`${outputFilename}.baseline.xlsx`);
            const freshOutPath = testInfo.outputPath(`${outputFilename}.fresh.xlsx`);
            await writeFile(baselineOutPath, baselineBytes);
            await writeFile(freshOutPath, freshBytes);

            if (generatedExecutionId) {
                testInfo.annotations.push({ type: 'noetl_execution_id', description: generatedExecutionId });
            }
            if (generatedExecutionStatus) {
                const statusOutPath = testInfo.outputPath(`${outputFilename}.noetl_execution_status.json`);
                await writeFile(statusOutPath, JSON.stringify(generatedExecutionStatus, null, 2));
                testInfo.annotations.push({ type: 'noetl_execution_status_path', description: statusOutPath });
            }
            if (generatedGcsUriCandidates && generatedGcsUriCandidates.length > 0) {
                const candidatesOutPath = testInfo.outputPath(`${outputFilename}.noetl_gcs_uri_candidates.json`);
                await writeFile(candidatesOutPath, JSON.stringify(generatedGcsUriCandidates, null, 2));
                testInfo.annotations.push({ type: 'noetl_gcs_uri_candidates_path', description: candidatesOutPath });
            }

            testInfo.annotations.push({ type: 'baseline_gcs_uri', description: baselineGsUri });
            testInfo.annotations.push({ type: 'fresh_gcs_uri', description: freshGsUri });
            testInfo.annotations.push({ type: 'baseline_excel_path', description: baselineOutPath });
            testInfo.annotations.push({ type: 'fresh_excel_path', description: freshOutPath });
            console.log(`[E2E] Baseline Excel saved to: ${baselineOutPath}`);
            console.log(`[E2E] Fresh Excel saved to: ${freshOutPath}`);
            console.log(`[E2E] Baseline source: ${baselineGsUri}`);
            console.log(`[E2E] Fresh source: ${freshGsUri}`);
        });

        // Final regression check: compare the parsed samples.
        await test.step('Compare fresh Excel to baseline (etalon)', async () => {
            // Fail fast with a clearer message when the generated report is a placeholder/empty workbook.
            const baselineHasManySheets = baselineSample.sheet_names.length > 1;
            const freshLooksEmpty =
                freshSample.sheet_names.length === 1 &&
                freshSample.sheet_names[0] === 'Sheet1' &&
                freshSample.sheets['Sheet1']?.row_count === 0;
            if (baselineHasManySheets && freshLooksEmpty) {
                throw new Error(
                    `Generated Excel looks empty (only Sheet1 with 0 rows), but baseline has ${baselineSample.sheet_names.length} sheets. ` +
                    `Likely the playbook '${playbookPath}' is producing an empty report in this environment, or reading from the wrong data source. ` +
                    `Check the saved NoETL status JSON in the Playwright test-results for details.`
                );
            }
            expect(freshSample).toEqual(baselineSample);
        });

        // Optional: update a committed JSON snapshot for quick baseline inspection.
        await test.step('Optionally save baseline sample snapshot (debug)', async () => {
            if (!UPDATE_EXCEL_SAMPLE) return;
            await writeJsonPretty(EXCEL_SAMPLE_PATH, baselineSample);
            console.log(`[E2E] Updated baseline Excel sample snapshot: ${EXCEL_SAMPLE_PATH}`);
        });

    });
});
