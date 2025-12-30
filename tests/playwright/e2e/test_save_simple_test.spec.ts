import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = process.env.NOETL_BASE_URL;

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

        await test.step('Wait: execution emits playbook.completed (reload)', async () => {
            await expect
                .poll(
                    async () => {
                        await page.reload();
                        await expect(page).toHaveTitle('NoETL Dashboard');

                        const rows = page.locator('.ant-table-wrapper .ant-table-row');
                        const rowCount = await rows.count();

                        const tableData: Record<string, string>[] = [];
                        for (let i = 0; i < rowCount; i++) {
                            const cells = rows.nth(i).locator('td');
                            const values = await cells.allTextContents();
                            tableData.push(Object.fromEntries(viewHeaders.map((key, idx) => [key, values[idx]])));
                        }

                        return tableData.some(
                            r =>
                                r['Event Type'] === 'playbook.completed' &&
                                r['Node Name'] === PLAYBOOK_CATALOG_NODE &&
                                r['Status'] === 'COMPLETED'
                        );
                    },
                    { timeout: 60000, intervals: [1000, 2000, 5000] }
                )
                .toBeTruthy();
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

            const validateCommandStep = async (stepName: string) => {
                await test.step(`Validate: ${stepName} step`, async () => {
                    expect(hasEvent('command.issued', stepName, 'PENDING')).toBeTruthy();
                    expect(hasEvent('step.enter', stepName, 'STARTED')).toBeTruthy();
                    expect(hasEvent('step.exit', stepName, 'COMPLETED')).toBeTruthy();
                    expect(hasEvent('command.completed', stepName, 'COMPLETED')).toBeTruthy();
                });
            };

            const validateIssuedClaimedOnly = async (stepName: string) => {
                await test.step(`Validate: ${stepName} command issued + claimed`, async () => {
                    expect(hasEvent('command.issued', stepName, 'PENDING')).toBeTruthy();
                    expect(hasEvent('command.claimed', stepName, 'RUNNING')).toBeTruthy();
                });
            };

            await test.step('Validate: playbook/workflow lifecycle', async () => {
                expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
                expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();
            });

            await validateCommandStep('start');
            await validateCommandStep('create_tables');
            await validateCommandStep('truncate_tables');

            await test.step('Validate: event_test step (+ sink claimed)', async () => {
                await validateCommandStep('event_test');
                await validateIssuedClaimedOnly('event_test_sink');
            });

            await test.step('Validate: postgres_flat_test step (+ sink)', async () => {
                await validateCommandStep('postgres_flat_test');
                await validateCommandStep('postgres_flat_test_sink');
            });

            await test.step('Validate: postgres_nested_test step (+ sink)', async () => {
                await validateCommandStep('postgres_nested_test');
                await validateCommandStep('postgres_nested_test_sink');
            });

            await test.step('Validate: end + workflow/playbook completion', async () => {
                await validateCommandStep('end');
                expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
            });
        });
    });
});