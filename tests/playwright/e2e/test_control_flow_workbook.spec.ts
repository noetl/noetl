import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import * as dotenv from 'dotenv';

dotenv.config();

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'control_flow_workbook';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/${PLAYBOOK_NAME}/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/${PLAYBOOK_NAME}`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Control flow workbook', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`./bin/noetl --host ${NOETL_HOST} --port ${NOETL_PORT} register playbook --file "${PLAYBOOK_PATH}"`, { stdio: 'inherit' });
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
            // (visible is optional, but detached is required)
        });

        await test.step('Wait for execution to complete and reload', async () => {
            await page.waitForTimeout(10000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Validate: events table contains expected lifecycle and step events', async () => {
            const rows = page.locator('.ant-table-wrapper .ant-table-row');
            await expect(rows.first()).toBeVisible();

            const rowCount = await rows.count();

            const tableData: Record<string, string>[] = [];
            for (let i = 0; i < rowCount; i++) {
                const cells = rows.nth(i).locator('td');
                const values = await cells.allTextContents();
                tableData.push(Object.fromEntries(viewHeaders.map((key, idx) => [key, values[idx]])));
            }

            console.log(tableData);

            const hasEvent = (eventType: string, nodeName: string, status?: string) =>
                tableData.some(
                    r =>
                        r['Event Type'] === eventType &&
                        r['Node Name'] === nodeName &&
                        (status ? r['Status'] === status : true)
                );

            const checkEvent = async (eventType: string, nodeName: string, status?: string) => {
                const label = status
                    ? `${eventType} → ${nodeName} [${status}]`
                    : `${eventType} → ${nodeName}`;
                await test.step(`Check: ${label}`, async () => {
                    expect(hasEvent(eventType, nodeName, status),
                        `Expected event not found: ${label}`).toBeTruthy();
                });
            };

            await checkEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED');
            await checkEvent('workflow.initialized', 'workflow', 'INITIALIZED');

            await checkEvent('command.issued', 'start', 'PENDING');
            await checkEvent('step.exit', 'start', 'COMPLETED');

            await checkEvent('command.issued', 'eval_flag', 'PENDING');
            await checkEvent('step.exit', 'eval_flag', 'COMPLETED');

            await checkEvent('command.issued', 'hot_path', 'PENDING');
            await checkEvent('step.exit', 'hot_path', 'COMPLETED');

            await checkEvent('command.issued', 'hot_task_a', 'PENDING');
            await checkEvent('step.exit', 'hot_task_a', 'COMPLETED');

            await checkEvent('command.issued', 'hot_task_b', 'PENDING');
            await checkEvent('step.exit', 'hot_task_b', 'COMPLETED');

            await checkEvent('workflow.completed', 'workflow', 'COMPLETED');
            await checkEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED');
        });
    });
});
