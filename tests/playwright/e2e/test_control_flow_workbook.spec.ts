import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('Control flow workbook', () => {

    // Run the registration command before all tests in this suite
    test.beforeAll(() => {
        console.log('Registering control_flow_workbook...');
        execSync('noetl register tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml --host localhost --port 8082', { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "control_flow_workbook"
        const exampleItem = page.locator("(//*[text()='control_flow_workbook']/following::button[normalize-space()='Execute'])[1]");

        // Inside that element, find the child with text "Execute" and click it
        await exampleItem.click();

        // wait until URL contains "/execution"
        await page.waitForURL('**/execution', { timeout: 60000 });

        // now check
        await expect(page.url()).toContain('/execution');

        const headers = [
            'Execution ID',
            'Playbook',
            'Status',
            'Progress',
            'Start Time',
            'Duration',
            'Actions'
        ];

        // Choose the first row of the table
        const row = page.locator('.ant-table-tbody > tr:first-child');
        const cells = row.locator('td');

        // Get all text contents of the cells in the row
        const values = await cells.allTextContents();

        // Map headers to their corresponding values
        const rowData = Object.fromEntries(headers.map((key, i) => [key, values[i]]));

        console.log(rowData);

        // Assertions
        await expect(rowData.Playbook).toBe('control_flow_workbook');
        await expect(rowData.Status).toBe('Running');
        await expect(rowData.Duration).toBe('8h 0m');

        // Wait a bit for the execution to complete
        await page.waitForTimeout(10000);
        // Refresh the page
        await page.reload();

        // Choose the first row of the table again
        const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
        const updatedCells = updatedRow.locator('td');
        // Get all text contents of the cells in the row
        const updatedValues = await updatedCells.allTextContents();
        // Map headers to their corresponding values
        const updatedRowData = Object.fromEntries(headers.map((key, i) => [key, updatedValues[i]]));

        console.log(updatedRowData);

        // Assert changes
        await expect(page).toHaveTitle('NoETL Dashboard');
        await expect(updatedRowData.Status).toBe('Completed');
        // await expect(updatedRowData.Playbook).toBe('control_flow_workbook');

        // Click the "View" button for the "control_flow_workbook" task
        // TODO fix the selector below from "Unknown" to "control_flow_workbook"
        const viewButton = await page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
        await viewButton.click();

        // View table headers
        const viewHeaders = [
            'Event Type',
            'Node Name',
            'Status',
            'Timestamp',
            'Duration'
        ];

        // Choose all rows of the table
        const rows = page.locator('.ant-table-wrapper .ant-table-row');
        const rowCount = await rows.count();

        const tableData: Record<string, string>[] = [];

        for (let i = 0; i < rowCount; i++) {
            const cells = rows.nth(i).locator('td');
            const values = await cells.allTextContents();

            // Create an object mapping headers to their corresponding values
            const rowData = Object.fromEntries(viewHeaders.map((key, idx) => [key, values[idx]]));
            tableData.push(rowData);
        }

        // Output the resulting table data
        console.log(tableData);

        // Example assert control_flow_workbook
        await expect(tableData[0]['Event Type']).toBe('execution_start');
        await expect(tableData[0]['Node Name']).toBe('control_flow_workbook');
        await expect(tableData[0].Status).toBe('IN_PROGRESS');

        // Example assert step_started
        await expect(tableData[1]['Event Type']).toBe('step_started');
        await expect(tableData[1]['Node Name']).toBe('eval_flag');
        await expect(tableData[1].Status).toBe('RUNNING');

        // Example assert action_started
        await expect(tableData[2]['Event Type']).toBe('action_started');
        await expect(tableData[2]['Node Name']).toBe('compute_flag');
        await expect(tableData[2].Status).toBe('RUNNING');

        // Example assert action_completed
        await expect(tableData[3]['Event Type']).toBe('action_completed');
        await expect(tableData[3]['Node Name']).toBe('compute_flag');
        await expect(tableData[3].Status).toBe('COMPLETED');

        // Example assert step_completed (compute_flag)
        await expect(tableData[4]['Event Type']).toBe('step_completed');
        await expect(tableData[4]['Node Name']).toBe('compute_flag');
        await expect(tableData[4].Status).toBe('COMPLETED');

        // Example assert step_result (compute_flag)
        await expect(tableData[5]['Event Type']).toBe('step_result');
        await expect(tableData[5]['Node Name']).toBe('compute_flag');
        await expect(tableData[5].Status).toBe('COMPLETED');

        // Example assert step_completed (eval_flag) — first occurrence
        await expect(tableData[6]['Event Type']).toBe('step_completed');
        await expect(tableData[6]['Node Name']).toBe('eval_flag');
        await expect(tableData[6].Status).toBe('COMPLETED');

        // Example assert step_completed (eval_flag) — second occurrence
        await expect(tableData[7]['Event Type']).toBe('step_completed');
        await expect(tableData[7]['Node Name']).toBe('eval_flag');
        await expect(tableData[7].Status).toBe('COMPLETED');

        // Example assert step_completed (hot_path) — first occurrence
        await expect(tableData[8]['Event Type']).toBe('step_completed');
        await expect(tableData[8]['Node Name']).toBe('hot_path');
        await expect(tableData[8].Status).toBe('COMPLETED');

        // Example assert step_completed (hot_path) — second occurrence
        await expect(tableData[9]['Event Type']).toBe('step_completed');
        await expect(tableData[9]['Node Name']).toBe('hot_path');
        await expect(tableData[9].Status).toBe('COMPLETED');
    });

});
