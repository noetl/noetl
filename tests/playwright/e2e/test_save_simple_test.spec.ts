import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;

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
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached', timeout: 30000 }).catch(() => { });
        });
        await test.step('Validate: events table contains expected lifecycle and step events', async () => {
            const rows = page.locator('.ant-table-wrapper .ant-table-row');
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

            await test.step('Validate: playbook/workflow lifecycle', async () => {
                expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
                expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();
            });

            await test.step('Validate: start step', async () => {
                expect(hasEvent('command.issued', 'start', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'start', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'start', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'start', 'COMPLETED')).toBeTruthy();
            });

            await test.step('Validate: create_tables step', async () => {
                expect(hasEvent('command.issued', 'create_tables', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'create_tables', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'create_tables', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'create_tables', 'COMPLETED')).toBeTruthy();
            });

            await test.step('Validate: truncate_tables step', async () => {
                expect(hasEvent('command.issued', 'truncate_tables', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'truncate_tables', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'truncate_tables', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'truncate_tables', 'COMPLETED')).toBeTruthy();
            });

            await test.step('Validate: event_test step (+ sink claimed)', async () => {
                expect(hasEvent('command.issued', 'event_test', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'event_test', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'event_test', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'event_test', 'COMPLETED')).toBeTruthy();

                expect(hasEvent('command.issued', 'event_test_sink', 'PENDING')).toBeTruthy();
                expect(hasEvent('command.claimed', 'event_test_sink', 'RUNNING')).toBeTruthy();
            });

            await test.step('Validate: postgres_flat_test step (+ sink)', async () => {
                expect(hasEvent('command.issued', 'postgres_flat_test', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'postgres_flat_test', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'postgres_flat_test', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'postgres_flat_test', 'COMPLETED')).toBeTruthy();

                expect(hasEvent('command.issued', 'postgres_flat_test_sink', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'postgres_flat_test_sink', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'postgres_flat_test_sink', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'postgres_flat_test_sink', 'COMPLETED')).toBeTruthy();
            });

            await test.step('Validate: postgres_nested_test step (+ sink)', async () => {
                expect(hasEvent('command.issued', 'postgres_nested_test', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'postgres_nested_test', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'postgres_nested_test', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'postgres_nested_test', 'COMPLETED')).toBeTruthy();

                expect(hasEvent('command.issued', 'postgres_nested_test_sink', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'postgres_nested_test_sink', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'postgres_nested_test_sink', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'postgres_nested_test_sink', 'COMPLETED')).toBeTruthy();
            });

            await test.step('Validate: end + workflow/playbook completion', async () => {
                expect(hasEvent('command.issued', 'end', 'PENDING')).toBeTruthy();
                expect(hasEvent('step.enter', 'end', 'STARTED')).toBeTruthy();
                expect(hasEvent('step.exit', 'end', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('command.completed', 'end', 'COMPLETED')).toBeTruthy();

                expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
            });
        });
    });
});