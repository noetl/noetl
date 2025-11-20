import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'tests/fixtures/playbooks/control_flow_workbook';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml';

test.describe('Control flow workbook', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should open catalog page and validate execution events', async ({ page }) => {

        let executionRowData: Record<string, string>;
        let updatedExecutionRowData: Record<string, string>;
        let eventTableData: Record<string, string>[] = [];

        const executionHeaders = [
            'Execution ID',
            'Playbook',
            'Status',
            'Progress',
            'Start Time',
            'Duration',
            'Actions'
        ];

        const eventHeaders = [
            'Event Type',
            'Node Name',
            'Status',
            'Timestamp',
            'Duration'
        ];

        await test.step('Navigate to catalog page', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Find playbook and execute it', async () => {
            const executeBtn = page.locator(`(//*[text()='control_flow_workbook']/following::button[normalize-space()='Execute'])[1]`);
            await executeBtn.click();
            await page.waitForURL('**/execution', { timeout: 60000 });
            await expect(page.url()).toContain('/execution');
        });

        await test.step('Wait for execution table to load and read first row', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });

            const row = page.locator('.ant-table-tbody > tr:first-child');
            const cells = row.locator('td');
            const values = await cells.allTextContents();
            executionRowData = Object.fromEntries(executionHeaders.map((k, i) => [k, values[i]]));
            console.log(executionRowData);

            await expect(executionRowData.Playbook).toBe(PLAYBOOK_ID);
            await expect(executionRowData.Status).toBe('RUNNING');
            await expect(executionRowData.Duration).toBe('3h 0m');
        });

        await test.step('Wait for completion and refresh table', async () => {
            await page.waitForTimeout(10000);
            await page.reload();

            const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
            const updatedCells = updatedRow.locator('td');
            const updatedValues = await updatedCells.allTextContents();
            updatedExecutionRowData = Object.fromEntries(executionHeaders.map((k, i) => [k, updatedValues[i]]));

            console.log(updatedExecutionRowData);

            await expect(page).toHaveTitle('NoETL Dashboard');
            await expect(updatedExecutionRowData.Status).toBe('COMPLETED');
        });

        await test.step('Open execution detail view', async () => {
            const viewButton = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='View'])[1]`);
            await viewButton.click();
            // Wait for URL change (adjust if another path is used)
            await page.waitForURL(/.*\/execution\/.+/, { timeout: 15000 }).catch(() => { });
            // Wait for table skeleton/spinner to disappear if present
            const loading = page.locator("//*[text()='Loading events...']");
            if (await loading.first().isVisible()) {
                await loading.first().waitFor({ state: 'detached', timeout: 20000 }).catch(() => { });
            }
        });

        await test.step('Wait for events table to populate', async () => {
            await test.step('Open all events', async () => {
                await page.click("//span[text()='10 / page']");
                const allOption = page.locator("//div[text()='100 / page']");
                await allOption.click();
            });
            await page.waitForSelector('.ant-table-wrapper .ant-table-row', { timeout: 20000 });
            // Now expect at least 20 events
            await expect.poll(async () => {
                return await page.locator('.ant-table-wrapper .ant-table-row').count();
            }, { timeout: 30000, intervals: [500] }).toBeGreaterThanOrEqual(20);
        });

        await test.step('Collect execution events table data', async () => {
            const rows = page.locator('.ant-table-wrapper .ant-table-row');
            const count = await rows.count();
            eventTableData = [];
            for (let i = 0; i < count; i++) {
                const cells = rows.nth(i).locator('td');
                const values = await cells.allTextContents();
                const obj = Object.fromEntries(eventHeaders.map((h, idx) => [h, values[idx] || '']));
                eventTableData.push(obj);
            }
            expect(eventTableData.length).toBeGreaterThanOrEqual(20);
        });

        await test.step('Validate full execution event sequence', async () => {
            const expected = [
                { type: 'playbook_started', node: PLAYBOOK_ID, status: 'STARTED' },
                { type: 'workflow_initialized', node: 'workflow', status: 'COMPLETED' },
                { type: 'step_started', node: 'eval_flag', status: 'RUNNING' },
                { type: 'action_started', node: 'eval_flag', status: 'RUNNING' },
                { type: 'action_completed', node: 'eval_flag', status: 'COMPLETED' },
                { type: 'step_completed', node: 'eval_flag', status: 'COMPLETED' },
                { type: 'step_completed', node: 'hot_path', status: 'COMPLETED' },
                { type: 'step_started', node: 'hot_task_a', status: 'RUNNING' },
                { type: 'step_started', node: 'hot_task_b', status: 'RUNNING' },
                { type: 'step_result', node: 'eval_flag', status: 'COMPLETED' },
                { type: 'action_started', node: 'hot_task_a', status: 'RUNNING' },
                { type: 'action_completed', node: 'hot_task_a', status: 'COMPLETED' },
                { type: 'step_completed', node: 'hot_task_a', status: 'COMPLETED' },
                { type: 'step_result', node: 'hot_task_a', status: 'COMPLETED' },
                { type: 'action_started', node: 'hot_task_b', status: 'RUNNING' },
                { type: 'action_completed', node: 'hot_task_b', status: 'COMPLETED' },
                { type: 'step_completed', node: 'hot_task_b', status: 'COMPLETED' },
                { type: 'workflow_completed', node: 'workflow', status: 'COMPLETED' },
                { type: 'playbook_completed', node: PLAYBOOK_ID, status: 'COMPLETED' },
                { type: 'step_result', node: 'hot_task_b', status: 'COMPLETED' },
            ];

            for (let i = 0; i < expected.length; i++) {
                await expect(eventTableData[i]['Event Type']).toBe(expected[i].type);
                await expect(eventTableData[i]['Node Name']).toBe(expected[i].node);
                await expect(eventTableData[i].Status).toBe(expected[i].status);
            }

            // Duration sanity checks (where durations appear)
            const hasEvalResult = eventTableData.find(e => e['Event Type'] === 'step_result' && e['Node Name'] === 'eval_flag');
            if (hasEvalResult) {
                expect(hasEvalResult.Duration === '' || /s$/.test(hasEvalResult.Duration)).toBeTruthy();
            }
        });

    });

});
