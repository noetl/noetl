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
            await expect(page).toHaveURL(/\/execution(\/|$)/, { timeout: 30000 });
        });

        await test.step('Wait and reload for completion', async () => {
            await page.waitForTimeout(10000);
            await page.reload();
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
