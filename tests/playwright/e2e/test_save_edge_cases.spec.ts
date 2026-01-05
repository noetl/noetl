import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'save_edge_cases';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/save_storage_test/${PLAYBOOK_NAME}`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('Save edge cases', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl register "${PLAYBOOK_PATH}" --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should execute playbook and show expected events', async ({ page }) => {
        await test.step('Navigate: open Catalog', async () => {
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
        await test.step('Wait for completion, then reload', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
        });
        await test.step('Wait: executions loader finishes (if present)', async () => {
            const loader = page.locator(`//*[text()='${LOADING_EXECUTIONS_TEXT}']`);
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
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

            const validateCommandStepCompleted = async (stepName: string) => {
                await test.step(`Validate: ${stepName} step`, async () => {
                    expect(hasEvent('command.issued', stepName, 'PENDING')).toBeTruthy();
                    expect(hasEvent('step.enter', stepName, 'STARTED')).toBeTruthy();
                    expect(hasEvent('step.exit', stepName, 'COMPLETED')).toBeTruthy();
                    expect(hasEvent('command.completed', stepName, 'COMPLETED')).toBeTruthy();
                });
            };

            const validateCommandStepFailed = async (stepName: string) => {
                await test.step(`Validate: ${stepName} step (FAILED)`, async () => {
                    expect(hasEvent('command.issued', stepName, 'PENDING')).toBeTruthy();
                    expect(hasEvent('step.enter', stepName, 'STARTED')).toBeTruthy();
                    expect(hasEvent('step.exit', stepName, 'FAILED')).toBeTruthy();
                    expect(hasEvent('command.failed', stepName, 'FAILED')).toBeTruthy();
                });
            };

            await test.step('Validate: playbook/workflow lifecycle', async () => {
                expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
                expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();
            });

            await validateCommandStepCompleted('start');

            await validateCommandStepCompleted('test_mixed_types');
            await validateCommandStepCompleted('test_mixed_types_sink');

            await validateCommandStepCompleted('test_special_characters');
            await validateCommandStepCompleted('test_special_characters_sink');

            await validateCommandStepCompleted('test_empty_data');
            await validateCommandStepFailed('test_empty_data_sink');

            await validateCommandStepCompleted('test_large_payload');

            await validateCommandStepCompleted('test_error_recovery');
            await validateCommandStepCompleted('test_error_recovery_sink');

            await validateCommandStepCompleted('test_completion_summary');
            await validateCommandStepCompleted('test_completion_summary_sink');

            await validateCommandStepCompleted('end');

            await test.step('Validate: workflow/playbook completion', async () => {
                expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
            });
        });
    });
});
