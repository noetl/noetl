import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'user_profile_scorer';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/playbook_composition/user_profile_scorer.yaml';

test.describe('User Profile Scorer', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should execute playbook and validate row', async ({ page }) => {

        await test.step('Navigate to catalog', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
        });

        await test.step('Verify dashboard title', async () => {
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        const executeBtn = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='Execute'])[1]`);

        await test.step(`Execute ${PLAYBOOK_ID} playbook`, async () => {
            await executeBtn.click();
        });

        await test.step('Wait for execution page URL', async () => {
            await expect(page).toHaveURL(/\/execution(\/|$)/, { timeout: 30000 });
            await expect(page.url()).toContain('/execution');
        });

        await test.step('Wait for executions loader to disappear', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
        });

        const headers = [
            'Execution ID',
            'Playbook',
            'Status',
            'Progress',
            'Start Time',
            'Duration',
            'Actions'
        ];

        await test.step('Wait for completion and reload', async () => {
            await page.waitForTimeout(10000);
            await page.reload();
        });

        await test.step('Validate table headers (ARIA)', async () => {
            const headerCells = page.locator('thead >> role=columnheader');
            await expect(headerCells).toHaveCount(5);
            await expect(headerCells).toHaveText(['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration']);
        });

        await test.step('Validate events (first 3 columns only)', async () => {
            const rows = page.locator('.ant-table-tbody > tr.ant-table-row');
            await expect(rows).toHaveCount(44, { timeout: 15000 });

            const expected: [string, string, string][] = [
                ['playbook_started', 'tests/fixtures/playbooks/playbook_composition/user_profile_scorer', 'STARTED'],
                ['workflow_initialized', 'workflow', 'COMPLETED'],
                ['step_started', 'extract_user_data', 'RUNNING'],
                ['action_started', 'extract_user_data', 'RUNNING'],
                ['action_completed', 'extract_user_data', 'COMPLETED'],
                ['step_completed', 'extract_user_data', 'COMPLETED'],
                ['step_started', 'score_experience', 'RUNNING'],
                ['step_result', 'extract_user_data', 'COMPLETED'],
                ['action_started', 'score_experience', 'RUNNING'],
                ['action_completed', 'score_experience', 'COMPLETED'],
                ['step_completed', 'score_experience', 'COMPLETED'],
                ['step_started', 'score_performance', 'RUNNING'],
                ['step_result', 'score_experience', 'COMPLETED'],
                ['action_started', 'score_performance', 'RUNNING'],
                ['action_completed', 'score_performance', 'COMPLETED'],
                ['step_completed', 'score_performance', 'COMPLETED'],
                ['step_started', 'score_department', 'RUNNING'],
                ['step_result', 'score_performance', 'COMPLETED'],
                ['action_started', 'score_department', 'RUNNING'],
                ['action_completed', 'score_department', 'COMPLETED'],
                ['step_completed', 'score_department', 'COMPLETED'],
                ['step_started', 'score_age', 'RUNNING'],
                ['step_result', 'score_department', 'COMPLETED'],
                ['action_started', 'score_age', 'RUNNING'],
                ['action_completed', 'score_age', 'COMPLETED'],
                ['step_completed', 'score_age', 'COMPLETED'],
                ['step_started', 'compute_total_score', 'RUNNING'],
                ['step_result', 'score_age', 'COMPLETED'],
                ['action_started', 'compute_total_score', 'RUNNING'],
                ['action_completed', 'compute_total_score', 'COMPLETED'],
                ['step_completed', 'compute_total_score', 'COMPLETED'],
                ['step_started', 'determine_score_category', 'RUNNING'],
                ['step_result', 'compute_total_score', 'COMPLETED'],
                ['action_started', 'determine_score_category', 'RUNNING'],
                ['action_completed', 'determine_score_category', 'COMPLETED'],
                ['step_completed', 'determine_score_category', 'COMPLETED'],
                ['step_started', 'finalize_result', 'RUNNING'],
                ['step_result', 'determine_score_category', 'COMPLETED'],
                ['action_started', 'finalize_result', 'RUNNING'],
                ['action_completed', 'finalize_result', 'COMPLETED'],
                ['step_completed', 'finalize_result', 'COMPLETED'],
                ['playbook_completed', 'tests/fixtures/playbooks/playbook_composition/user_profile_scorer', 'COMPLETED'],
                ['workflow_completed', 'workflow', 'COMPLETED'],
                ['step_result', 'finalize_result', 'COMPLETED'],
            ];

            for (let i = 0; i < expected.length; i++) {
                const cells = rows.nth(i).locator('td');
                const cellTexts = await cells.allTextContents();
                const eventType = cellTexts[0]?.trim();
                const nodeName = cellTexts[1]?.trim();
                const status = cellTexts[2]?.replace(/\s+/g, ' ').trim();
                await expect(eventType).toBe(expected[i][0]);
                await expect(nodeName).toBe(expected[i][1]);
                await expect(status).toContain(expected[i][2]);
            }
        });

    });

});
