import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'create_tables';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}.yaml`;

const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Create Tables', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        await test.step('Open Catalog', async () => {
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

        await test.step('Wait for executions loader to finish (if present)', async () => {
            const loader = page.locator(`//*[text()='${LOADING_EXECUTIONS_TEXT}']`);
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
        });

        await test.step('Wait for completion, then reload', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
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

            // playbook/workflow lifecycle
            expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
            expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();

            // start step
            expect(hasEvent('command.issued', 'start', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'start', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'start', 'COMPLETED')).toBeTruthy();

            // create_flat_table step
            expect(hasEvent('command.issued', 'create_flat_table', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'create_flat_table', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'create_flat_table', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'create_flat_table', 'COMPLETED')).toBeTruthy();

            // create_nested_table step
            expect(hasEvent('command.issued', 'create_nested_table', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'create_nested_table', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'create_nested_table', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'create_nested_table', 'COMPLETED')).toBeTruthy();

            // create_summary_table step
            expect(hasEvent('command.issued', 'create_summary_table', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'create_summary_table', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'create_summary_table', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'create_summary_table', 'COMPLETED')).toBeTruthy();

            // end + completion
            expect(hasEvent('command.issued', 'end', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'end', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'end', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'end', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
        });
    });
});
