import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import * as dotenv from 'dotenv';

dotenv.config();

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'save_simple_test';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Save Simple Test', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl register "${PLAYBOOK_PATH}" --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should execute playbook and show expected events', async ({ page }) => {
        await test.step('Navigate: open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step(`Click: Execute "${PLAYBOOK_NAME}" and wait for navigation`, async () => {
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

            // "visible" is optional: loader might flash too fast or not appear at all.
            try {
                await loader.waitFor({ state: 'visible', timeout: 5000 });
            } catch {
                // ignore
            }

            // If loader appears and gets stuck, fail here (do not swallow).
            await loader.waitFor({ state: 'detached', timeout: 30000 });
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

            await checkEvent('command.issued', 'create_tables', 'PENDING');
            await checkEvent('step.exit', 'create_tables', 'COMPLETED');

            await checkEvent('command.issued', 'truncate_tables', 'PENDING');
            await checkEvent('step.exit', 'truncate_tables', 'COMPLETED');

            await checkEvent('command.issued', 'event_test', 'PENDING');
            await checkEvent('step.exit', 'event_test', 'COMPLETED');
            await checkEvent('command.issued', 'event_test_sink', 'PENDING');

            await checkEvent('command.issued', 'postgres_flat_test', 'PENDING');
            await checkEvent('step.exit', 'postgres_flat_test', 'COMPLETED');
            await checkEvent('command.issued', 'postgres_flat_test_sink', 'PENDING');
            await checkEvent('step.exit', 'postgres_flat_test_sink', 'COMPLETED');

            await checkEvent('command.issued', 'postgres_nested_test', 'PENDING');
            await checkEvent('step.exit', 'postgres_nested_test', 'COMPLETED');
            await checkEvent('command.issued', 'postgres_nested_test_sink', 'PENDING');

            await checkEvent('command.issued', 'end', 'PENDING');
            await checkEvent('step.exit', 'end', 'COMPLETED');

            await checkEvent('workflow.completed', 'workflow', 'COMPLETED');
            await checkEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED');
        });
    });
});