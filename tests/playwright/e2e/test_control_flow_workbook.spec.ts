import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'control_flow_workbook';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/${PLAYBOOK_NAME}/${PLAYBOOK_NAME}.yaml`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Control flow workbook', () => {
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

        await test.step('Wait for execution to complete and reload', async () => {
            await page.waitForTimeout(10000);
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

            expect(hasEvent('playbook.initialized', `tests/fixtures/playbooks/${PLAYBOOK_NAME}`, 'INITIALIZED')).toBeTruthy();
            expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();

            expect(hasEvent('step.enter', 'start', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'start', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('step.enter', 'eval_flag', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'eval_flag', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('step.enter', 'hot_path', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'hot_path', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'hot_task_a', 'PENDING')).toBeTruthy();
            expect(hasEvent('command.issued', 'hot_task_b', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.exit', 'hot_task_a', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('step.exit', 'hot_task_b', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('playbook.completed', `tests/fixtures/playbooks/${PLAYBOOK_NAME}`, 'COMPLETED')).toBeTruthy();
        });
    });
});
