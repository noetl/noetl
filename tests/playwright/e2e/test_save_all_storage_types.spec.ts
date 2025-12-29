import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'save_all_storage_types';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}`;
const LOADING_EXECUTIONS_TEXT = 'Loading executions...';
const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Save all storage types', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
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

            // initialize_test_data (+ sink issued)
            expect(hasEvent('command.issued', 'initialize_test_data', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'initialize_test_data', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'initialize_test_data', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'initialize_test_data', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.issued', 'initialize_test_data_sink', 'PENDING')).toBeTruthy();

            // test_flat_postgres_save (+ sink)
            expect(hasEvent('command.issued', 'test_flat_postgres_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_flat_postgres_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_flat_postgres_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_flat_postgres_save', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_flat_postgres_save_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_flat_postgres_save_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_flat_postgres_save_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_flat_postgres_save_sink', 'COMPLETED')).toBeTruthy();

            // test_nested_postgres_save (+ sink)
            expect(hasEvent('command.issued', 'test_nested_postgres_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_nested_postgres_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_nested_postgres_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_nested_postgres_save', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_nested_postgres_save_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_nested_postgres_save_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_nested_postgres_save_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_nested_postgres_save_sink', 'COMPLETED')).toBeTruthy();

            // test_postgres_statement_save (+ sink)
            expect(hasEvent('command.issued', 'test_postgres_statement_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_postgres_statement_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_postgres_statement_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_postgres_statement_save', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_postgres_statement_save_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_postgres_statement_save_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_postgres_statement_save_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_postgres_statement_save_sink', 'COMPLETED')).toBeTruthy();

            // test_python_save (+ sink FAIL in provided log)
            expect(hasEvent('command.issued', 'test_python_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_python_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_python_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_python_save', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_python_save_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_python_save_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_python_save_sink', 'FAILED')).toBeTruthy();
            expect(hasEvent('command.failed', 'test_python_save_sink', 'FAILED')).toBeTruthy();

            // test_duckdb_save
            expect(hasEvent('command.issued', 'test_duckdb_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_duckdb_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_duckdb_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_duckdb_save', 'COMPLETED')).toBeTruthy();

            // test_http_save (+ sink)
            expect(hasEvent('command.issued', 'test_http_save', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_http_save', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_http_save', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_http_save', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_http_save_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_http_save_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_http_save_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_http_save_sink', 'COMPLETED')).toBeTruthy();

            // test_completion (в предоставленном логе есть issued + enter; exit/completed не показаны)
            expect(hasEvent('command.issued', 'test_completion', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_completion', 'STARTED')).toBeTruthy();
        });

    });
});
