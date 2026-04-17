import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = process.env.NOETL_PORT;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;

const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'control_flow_workbook';
const PLAYBOOK_PATH = `tests/fixtures/playbooks/${PLAYBOOK_NAME}/${PLAYBOOK_NAME}.yaml`;
const PLAYBOOK_CATALOG_NODE = `tests/fixtures/playbooks/${PLAYBOOK_NAME}`;

const viewHeaders = ['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration'] as const;

type TableRow = Record<typeof viewHeaders[number], string>;

async function readEventsTablePage(page: Page): Promise<TableRow[]> {
    const rows = page.locator('[data-testid="events-table"] .ant-table-row');
    const rowCount = await rows.count();
    const tableData: TableRow[] = [];
    for (let i = 0; i < rowCount; i++) {
        const cells = rows.nth(i).locator('td');
        const values = await cells.allTextContents();
        tableData.push(Object.fromEntries(viewHeaders.map((key, idx) => [key, values[idx]])) as TableRow);
    }
    return tableData;
}

async function readEventsTable(page: Page): Promise<TableRow[]> {
    await page.waitForLoadState('networkidle').catch(() => {});
    const allData: TableRow[] = [];
    while (true) {
        const pageData = await readEventsTablePage(page);
        allData.push(...pageData);
        const nextBtn = page.locator('[data-testid="events-table"] .ant-pagination-next:not(.ant-pagination-disabled)');
        if (await nextBtn.count() === 0) break;
        await nextBtn.click();
        await page.waitForTimeout(300);
    }
    return allData;
}

function hasEvent(tableData: TableRow[], eventType: string, nodeName: string, status?: string): boolean {
    return tableData.some(r =>
        r['Event Type'] === eventType &&
        r['Node Name'] === nodeName &&
        (status ? r['Status'] === status : true)
    );
}

test.describe('Control flow workbook', () => {
    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_NAME}...`);
        execSync(`noetl --host ${NOETL_HOST} --port ${NOETL_PORT} register playbook --file ${PLAYBOOK_PATH}`, { stdio: 'inherit' });
    });

    test('should execute and emit expected control flow events', async ({ page }) => {
        await test.step('Navigate: open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step(`Execute "${PLAYBOOK_NAME}" from Catalog`, async () => {
            const executeButton = page.locator(`[data-testid="catalog-execute-${PLAYBOOK_NAME}"]`).first();
            await executeButton.click();
            await expect(page).toHaveURL(/\/execution/);
        });

        await test.step('Wait: executions loader finishes (if present)', async () => {
            const loader = page.locator('[data-testid="execution-loading"]');
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
            await loader.waitFor({ state: 'detached', timeout: 30000 });
        });

        await test.step('Wait for execution to complete, then reload', async () => {
            await page.waitForTimeout(10000);
            await page.reload();
            await expect(page).toHaveTitle('NoETL Dashboard');
        });


        await test.step('Poll: wait for playbook.completed', async () => {
            await expect
                .poll(
                    async () => {
                        await page.reload();
                        await expect(page).toHaveTitle('NoETL Dashboard');
                        const tableData = await readEventsTable(page);
                        return hasEvent(tableData, 'playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED');
                    },
                    { timeout: 60000, intervals: [1000, 2000, 5000] }
                )
                .toBeTruthy();
        });

        await test.step('Validate: control flow events present', async () => {
            const tableData = await readEventsTable(page);
            console.log(tableData);

            expect(hasEvent(tableData, 'playbook.initialized', PLAYBOOK_CATALOG_NODE, 'INITIALIZED')).toBeTruthy();
            expect(hasEvent(tableData, 'workflow.initialized', 'workflow', 'INITIALIZED')).toBeTruthy();

            expect(hasEvent(tableData, 'step.enter', 'start', 'RUNNING')).toBeTruthy();
            expect(hasEvent(tableData, 'step.exit', 'start', 'COMPLETED')).toBeTruthy();

            expect(hasEvent(tableData, 'step.enter', 'eval_flag', 'RUNNING')).toBeTruthy();
            expect(hasEvent(tableData, 'step.exit', 'eval_flag', 'COMPLETED')).toBeTruthy();

            expect(hasEvent(tableData, 'step.enter', 'hot_path', 'RUNNING')).toBeTruthy();
            expect(hasEvent(tableData, 'step.exit', 'hot_path', 'COMPLETED')).toBeTruthy();

            expect(hasEvent(tableData, 'command.issued', 'hot_task_a', 'PENDING')).toBeTruthy();
            expect(hasEvent(tableData, 'command.issued', 'hot_task_b', 'PENDING')).toBeTruthy();
            expect(hasEvent(tableData, 'step.exit', 'hot_task_a', 'COMPLETED')).toBeTruthy();
            expect(hasEvent(tableData, 'step.exit', 'hot_task_b', 'COMPLETED')).toBeTruthy();

            expect(hasEvent(tableData, 'workflow.completed', 'workflow', 'COMPLETED')).toBeTruthy();
            expect(hasEvent(tableData, 'playbook.completed', PLAYBOOK_CATALOG_NODE, 'COMPLETED')).toBeTruthy();
        });
    });
});
