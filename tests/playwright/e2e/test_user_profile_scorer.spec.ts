import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'user_profile_scorer';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/playbook_composition/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/playbook_composition/${PLAYBOOK_NAME}`;

const LOADING_EXECUTIONS_TEXT = 'Loading executions...';

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

test.describe('User Profile Scorer', () => {
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

        await test.step('Wait: executions loader finishes (if present)', async () => {
            const loader = page.locator(`//*[text()='${LOADING_EXECUTIONS_TEXT}']`);
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached', timeout: 30000 }).catch(() => { });
        });
        await test.step('Wait for completion, then reload', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
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

            const validateCommandStep = async (stepName: string) => {
                await test.step(`Validate: ${stepName} step`, async () => {
                    expect(hasEvent('command.issued', stepName, 'PENDING')).toBeTruthy();
                    expect(hasEvent('step.enter', stepName, 'STARTED')).toBeTruthy();
                    expect(hasEvent('step.exit', stepName, 'COMPLETED')).toBeTruthy();
                    expect(hasEvent('command.completed', stepName, 'COMPLETED')).toBeTruthy();
                });
            };

            await test.step('Validate: playbook/workflow lifecycle', async () => {
                expect(hasEvent('playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
                expect(hasEvent('workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();
            });

            await validateCommandStep('start');
            await validateCommandStep('extract_user_data');
            await validateCommandStep('score_experience');
            await validateCommandStep('score_performance');
            await validateCommandStep('score_department');
            await validateCommandStep('score_age');
            await validateCommandStep('compute_total_score');
            await validateCommandStep('determine_score_category');
            await validateCommandStep('finalize_result');

            await test.step('Validate: workflow/playbook completion', async () => {
                expect(hasEvent('workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
                expect(hasEvent('playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
            });
        });
    });
});