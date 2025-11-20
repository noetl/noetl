import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'tests/fixtures/playbooks/save_storage_test/create_tables';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/save_storage_test/create_tables.yaml';

test.describe('Create Tables', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should execute create_tables playbook and open execution detail', async ({ page }) => {

        const executionHeaders = [
            'Execution ID', 'Playbook', 'Status', 'Progress', 'Start Time', 'Duration', 'Actions'
        ];
        const eventHeaders = [
            'Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'
        ];

        let initialRowData: Record<string, string>;
        let updatedRowData: Record<string, string>;
        let eventTableData: Record<string, string>[] = [];

        await test.step('Navigate to catalog page', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Execute playbook', async () => {
            const executeBtn = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='Execute'])[1]`);
            await executeBtn.click();
            await page.waitForURL('**/execution', { timeout: 60000 });
            await expect(page.url()).toContain('/execution');
        });

        await test.step('Wait for executions table loader and capture initial row', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached', timeout: 10000 }).catch(() => { });

            const row = page.locator('.ant-table-tbody > tr:first-child');
            await expect(row).toBeVisible();

            const cells = row.locator('td');
            await expect(cells.first()).toHaveText(/.+/);
            const values = await cells.allTextContents();
            initialRowData = Object.fromEntries(executionHeaders.map((h, i) => [h, values[i] ?? '']));
            console.log('Initial row:', initialRowData);

            await expect(initialRowData.Playbook).toBe(PLAYBOOK_ID);
            // Depending on backend this may be STARTED or RUNNING; try flexible assertion:
            expect(['STARTED', 'RUNNING']).toContain(initialRowData.Status);
        });

        await test.step('Poll until execution completes', async () => {
            await expect.poll(async () => {
                await page.reload();
                const row = page.locator('.ant-table-tbody > tr:first-child');
                const vals = await row.locator('td').allTextContents();
                updatedRowData = Object.fromEntries(executionHeaders.map((h, i) => [h, vals[i] ?? '']));
                return updatedRowData.Status;
            }, { timeout: 30000, intervals: [1500] }).toBe('COMPLETED');
            console.log('Updated row:', updatedRowData);
        });

        await test.step('Open execution detail view', async () => {
            // Preferred locator by playbook id
            let viewButton = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='View'])[1]`);
            if (!(await viewButton.first().isVisible())) {
                // Fallback for legacy / Unknown label
                viewButton = page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
            }
            await viewButton.click();
            await page.waitForURL(/.*\/execution\/.+/, { timeout: 20000 }).catch(() => { });
        });

        await test.step('Wait for events loader to disappear (if present)', async () => {
            const eventsLoader = page.locator("//*[text()='Loading events...']");
            if (await eventsLoader.first().isVisible()) {
                await eventsLoader.first().waitFor({ state: 'detached', timeout: 20000 }).catch(() => { });
            }
        });

        await test.step('Open all events', async () => {
            await page.click("//span[text()='10 / page']").catch(() => { });
            const allOption = page.locator("//div[text()='100 / page']");
            await allOption.click();
        });

        await test.step('Wait for full events list (>=19 rows)', async () => {
            await page.waitForSelector('.ant-table-wrapper .ant-table-row', { timeout: 20000 });
            await expect.poll(async () => {
                return await page.locator('.ant-table-wrapper .ant-table-row').count();
            }, { timeout: 30000, intervals: [500] }).toBeGreaterThanOrEqual(19);
        });

        await test.step('Collect execution events table data', async () => {
            const rows = page.locator('.ant-table-wrapper .ant-table-row');
            const count = await rows.count();
            for (let i = 0; i < count; i++) {
                const cells = rows.nth(i).locator('td');
                const values = await cells.allTextContents();
                const obj = Object.fromEntries(eventHeaders.map((h, idx) => [h, values[idx] || '']));
                eventTableData.push(obj);
            }
            expect(eventTableData.length).toBeGreaterThanOrEqual(19);
        });

        await test.step('Validate full execution event sequence', async () => {
            const expected = [
                { type: 'playbook_started', node: PLAYBOOK_ID, status: 'STARTED' },
                { type: 'workflow_initialized', node: 'workflow', status: 'COMPLETED' },
                { type: 'step_started', node: 'create_flat_table', status: 'RUNNING' },
                { type: 'action_started', node: 'create_flat_table', status: 'RUNNING' },
                { type: 'action_completed', node: 'create_flat_table', status: 'COMPLETED' },
                { type: 'step_completed', node: 'create_flat_table', status: 'COMPLETED' },
                { type: 'step_started', node: 'create_nested_table', status: 'RUNNING' },
                { type: 'step_result', node: 'create_flat_table', status: 'COMPLETED' },
                { type: 'action_started', node: 'create_nested_table', status: 'RUNNING' },
                { type: 'action_completed', node: 'create_nested_table', status: 'COMPLETED' },
                { type: 'step_completed', node: 'create_nested_table', status: 'COMPLETED' },
                { type: 'step_started', node: 'create_summary_table', status: 'RUNNING' },
                { type: 'step_result', node: 'create_nested_table', status: 'COMPLETED' },
                { type: 'action_started', node: 'create_summary_table', status: 'RUNNING' },
                { type: 'action_completed', node: 'create_summary_table', status: 'COMPLETED' },
                { type: 'step_completed', node: 'create_summary_table', status: 'COMPLETED' },
                { type: 'workflow_completed', node: 'workflow', status: 'COMPLETED' },
                { type: 'playbook_completed', node: PLAYBOOK_ID, status: 'COMPLETED' },
                { type: 'step_result', node: 'create_summary_table', status: 'COMPLETED' },
            ];

            for (let i = 0; i < expected.length; i++) {
                await expect(eventTableData[i]['Event Type']).toBe(expected[i].type);
                await expect(eventTableData[i]['Node Name']).toBe(expected[i].node);
                await expect(eventTableData[i].Status).toBe(expected[i].status);
            }

            // Validate per-task ordering
            function assertTaskSequence(task: string) {
                const idxStepStarted = eventTableData.findIndex(e => e['Event Type'] === 'step_started' && e['Node Name'] === task);
                const idxActionStarted = eventTableData.findIndex(e => e['Event Type'] === 'action_started' && e['Node Name'] === task);
                const idxActionCompleted = eventTableData.findIndex(e => e['Event Type'] === 'action_completed' && e['Node Name'] === task);
                const idxStepCompleted = eventTableData.findIndex(e => e['Event Type'] === 'step_completed' && e['Node Name'] === task);
                const idxStepResult = eventTableData.findIndex(e => e['Event Type'] === 'step_result' && e['Node Name'] === task);

                expect(idxStepStarted).toBeGreaterThanOrEqual(0);
                expect(idxActionStarted).toBeGreaterThan(idxStepStarted);
                expect(idxActionCompleted).toBeGreaterThan(idxActionStarted);
                expect(idxStepCompleted).toBeGreaterThan(idxActionCompleted);
                expect(idxStepResult).toBeGreaterThan(idxStepCompleted);
            }

            assertTaskSequence('create_flat_table');
            assertTaskSequence('create_nested_table');
            assertTaskSequence('create_summary_table');

            // Duration sanity
            const durationOk = (d: string) => d === '' || d === 'nulls' || /\d(\.\d+)?s$/.test(d);
            for (const row of eventTableData) {
                if (row.Duration) {
                    expect(durationOk(row.Duration)).toBeTruthy();
                }
            }
        });

    });

});
