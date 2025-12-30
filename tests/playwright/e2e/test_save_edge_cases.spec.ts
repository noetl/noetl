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

            // lifecycle
            expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
            expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();

            // start
            expect(hasEvent('command.issued', 'start', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'start', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'start', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'start', 'COMPLETED')).toBeTruthy();

            // test_mixed_types (+ sink)
            expect(hasEvent('command.issued', 'test_mixed_types', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_mixed_types', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_mixed_types', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_mixed_types', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_mixed_types_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_mixed_types_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_mixed_types_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_mixed_types_sink', 'COMPLETED')).toBeTruthy();

            // test_special_characters (+ sink)
            expect(hasEvent('command.issued', 'test_special_characters', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_special_characters', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_special_characters', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_special_characters', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_special_characters_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_special_characters_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_special_characters_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_special_characters_sink', 'COMPLETED')).toBeTruthy();

            // test_empty_data (+ sink FAILED)
            expect(hasEvent('command.issued', 'test_empty_data', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_empty_data', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_empty_data', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_empty_data', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_empty_data_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_empty_data_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_empty_data_sink', 'FAILED')).toBeTruthy();
            expect(hasEvent('command.failed', 'test_empty_data_sink', 'FAILED')).toBeTruthy();

            // test_large_payload
            expect(hasEvent('command.issued', 'test_large_payload', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_large_payload', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_large_payload', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_large_payload', 'COMPLETED')).toBeTruthy();

            // test_error_recovery (+ sink)
            expect(hasEvent('command.issued', 'test_error_recovery', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_error_recovery', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_error_recovery', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_error_recovery', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_error_recovery_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_error_recovery_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_error_recovery_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_error_recovery_sink', 'COMPLETED')).toBeTruthy();

            // test_completion_summary (+ sink)
            expect(hasEvent('command.issued', 'test_completion_summary', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_completion_summary', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_completion_summary', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_completion_summary', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('command.issued', 'test_completion_summary_sink', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'test_completion_summary_sink', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'test_completion_summary_sink', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'test_completion_summary_sink', 'COMPLETED')).toBeTruthy();

            // end + completion
            expect(hasEvent('command.issued', 'end', 'PENDING')).toBeTruthy();
            expect(hasEvent('step.enter', 'end', 'STARTED')).toBeTruthy();
            expect(hasEvent('step.exit', 'end', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('command.completed', 'end', 'COMPLETED')).toBeTruthy();

            expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
            expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
        });
    });
});
