import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;
const EXECUTION_URL_PATTERN = '**/execution*';

const PLAYBOOK_NAME = 'save_delegation_test';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}`;
const LOADING_EXECUTIONS_TEXT = 'Loading executions...';
const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;


test.describe('Save delegation test', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl register "${PLAYBOOK_PATH}" --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        await test.step('Navigate: open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step(`Execute ${PLAYBOOK_NAME} from Catalog`, async () => {
            const executeButton = page.locator(
                `(//*[text()='${PLAYBOOK_NAME}']/following::button[normalize-space()='Execute'])[1]`
            );
            await executeButton.click();
            await expect(page).toHaveURL(/\/execution/);
        });
        await test.step('Wait for completion, then reload', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
        });
        await test.step('Wait: executions loader finishes (if present)', async () => {
            const loader = page.locator(`//*[text()='${LOADING_EXECUTIONS_TEXT}']`);
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached', timeout: 30000 }).catch(() => { });
        });
        await test.step('Parse events table and validate key events', async () => {
            const rows = page.locator('.ant-table-wrapper .ant-table-row');
            const rowCount = await rows.count();

            const tableData: Record<string, string>[] = [];

            for (let i = 0; i < rowCount; i++) {
                const cells = rows.nth(i).locator('td');
                const values = await cells.allTextContents();
                const rowData = Object.fromEntries(viewHeaders.map((key, idx) => [key, values[idx]]));
                tableData.push(rowData);
            }

            console.log(tableData);

            const hasEvent = (eventType: string, nodeName: string, status?: string) =>
                tableData.some(r =>
                    r['Event Type'] === eventType &&
                    r['Node Name'] === nodeName &&
                    (status ? r['Status'] === status : true)
                );

            // lifecycle
            expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
            expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();

            // start
            expect(hasEvent('command.issued', 'start', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'start', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'start', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'start', 'COMPLETED')).toBeTruthy();

            // create_tables
            expect(hasEvent('command.issued', 'create_tables', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'create_tables', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'create_tables', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'create_tables', 'COMPLETED')).toBeTruthy();

            // truncate_tables
            expect(hasEvent('command.issued', 'truncate_tables', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'truncate_tables', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'truncate_tables', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'truncate_tables', 'COMPLETED')).toBeTruthy();

            // event_test (+ sink issued/claimed)
            expect(hasEvent('command.issued', 'event_test', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'event_test', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'event_test', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'event_test', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'event_test_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('command.claimed', 'event_test_sink', 'RUNNING')).toBeTruthy();

            // postgres_test (+ sink)
            expect(hasEvent('command.issued', 'postgres_test', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'postgres_test', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'postgres_test', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'postgres_test', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'postgres_test_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'postgres_test_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'postgres_test_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'postgres_test_sink', 'COMPLETED')).toBeTruthy();

            // duckdb_test
            expect(hasEvent('command.issued', 'duckdb_test', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'duckdb_test', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'duckdb_test', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'duckdb_test', 'COMPLETED')).toBeTruthy();

            // http_test (+ sink)
            expect(hasEvent('command.issued', 'http_test', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'http_test', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'http_test', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'http_test', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'http_test_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'http_test_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'http_test_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'http_test_sink', 'COMPLETED')).toBeTruthy();
        });

    });
});
