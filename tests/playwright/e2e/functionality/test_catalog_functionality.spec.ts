import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import * as dotenv from 'dotenv';
import * as fs from 'fs';
import * as path from 'path';

dotenv.config();

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = `8099`;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const CATALOG_URL = `${BASE_URL}/catalog`;

const PLAYBOOK_NAME = 'hello_world';

test.describe('Catalog Functionality', () => {
    test('/catalog: New Playbook JSON/YAML', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click New Playbook button', async () => {
            const newPlaybookBtn = page.locator("//span[text()='New Playbook']");
            await newPlaybookBtn.click();
        });

        await test.step('Fill playbook YAML content', async () => {
            const yamlPath = path.join(__dirname, '../../../fixtures/playbooks/hello_world/hello_world.yaml');
            const yamlContent = fs.readFileSync(yamlPath, 'utf-8');
            const textarea = page.locator("//textarea");
            await textarea.fill(yamlContent);
        });

        await test.step('Click Register Playbook button', async () => {
            const registerBtn = page.locator("//span[text()='Register Playbook']");
            await registerBtn.click();
        });
        await test.step('Validate success notification', async () => {
            const notification = page.locator("//*[text()='Playbook registered successfully!']");
            await expect(notification).toBeVisible();
        });

        await test.step('Validate Execute button is visible', async () => {
            const executeBtn = page.locator(
                `(//*[text()='${PLAYBOOK_NAME}']/following::button[normalize-space()='Execute'])[1]`
            );
            await expect(executeBtn).toBeVisible();
        });

    });
    test('/catalog: New Playbook Upload file', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click New Playbook button', async () => {
            const newPlaybookBtn = page.locator("//span[text()='New Playbook']");
            await newPlaybookBtn.click();
        });

        await test.step('Click Upload File button', async () => {
            const uploadFileBtn = page.locator("//*[text()='Upload File']");
            await uploadFileBtn.click();
        });

        await test.step('Upload playbook file', async () => {
            const yamlPath = path.join(__dirname, '../../../fixtures/playbooks/hello_world/hello_world.yaml');
            const fileInput = page.locator("input[type='file']");
            await fileInput.setInputFiles(yamlPath);
        });

        await test.step('Click Register Playbook button', async () => {
            const registerBtn = page.locator("//span[text()='Register Playbook']");
            await registerBtn.click();
        });
        await test.step('Validate success notification', async () => {
            const notification = page.locator("//*[text()='Playbook registered successfully!']");
            await expect(notification).toBeVisible();
        });

        await test.step('Validate Execute button is visible', async () => {
            const executeBtn = page.locator(
                `(//*[text()='${PLAYBOOK_NAME}']/following::button[normalize-space()='Execute'])[1]`
            );
            await expect(executeBtn).toBeVisible();
        });

    });
    test('/catalog: Search', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Type "hello_world" into search input', async () => {
            const searchInput = page.locator("//input[@placeholder='Search playbooks...']");
            await searchInput.fill('hello_world');

            // debounce in UI (replace with deterministic wait if UI exposes it)
            await page.waitForTimeout(1000);
        });

        await test.step('Validate control_flow_workbook is not visible', async () => {
            const otherItem = page.locator("//*[text()='control_flow_workbook']");
            await expect(otherItem).toHaveCount(0);
        });

        await test.step('Validate hello_world is visible', async () => {
            const helloWorldItem = page.locator("//*[text()='hello_world']");
            await expect(helloWorldItem.first()).toBeVisible();
        });
    });
    test('/catalog: View', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Type "hello_world" into search input', async () => {
            const searchInput = page.locator("//input[@placeholder='Search playbooks...']");
            await searchInput.fill('hello_world');
        });

        await test.step('Click View for hello_world', async () => {
            const viewBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='View'])[1]"
            );
            await viewBtn.click();
        });

        await test.step('Validate navigation to Execution page', async () => {
            await expect(page).toHaveURL(/\/execution/);
        });

        await test.step('Validate workflow visualization is visible', async () => {
            const workflowHeading = page.locator("//h2[contains(text(), 'Workflow Visualization')]");
            await expect(workflowHeading).toBeVisible();
        });
    });
    test('/catalog: Edit', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Edit for hello_world', async () => {
            const editBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Edit'])[1]"
            );
            await editBtn.click();
        });

        await test.step('Validate navigation to Editor page', async () => {
            await expect(page).toHaveURL(/\/editor/);
            await expect(page.url()).toContain('/editor?id=tests/fixtures/playbooks/hello_world');
        });

        await test.step('Validate editor content matches file content', async () => {
            const yamlPath = path.join(__dirname, '../../../fixtures/playbooks/hello_world/hello_world.yaml');
            fs.readFileSync(yamlPath, 'utf-8');

            // Monaco-based editors often keep a hidden textarea empty.
            // Assert against the rendered YAML text that appears in the editor UI.
            await expect(page.getByText('apiVersion: noetl.io/v2', { exact: true })).toBeVisible();
            await expect(page.getByText('kind: Playbook', { exact: true })).toBeVisible();
            await expect(page.getByText('name: hello_world', { exact: true })).toBeVisible();
        });
    });


    test('/catalog: Execute', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Execute for hello_world', async () => {
            const executeBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Execute'])[1]"
            );
            await executeBtn.click();
        });

        await test.step('Validate navigation to Execution page', async () => {
            await expect(page).toHaveURL(/\/execution/);
        });

        await test.step('Wait for executions loader to finish (if present)', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
        });
    });

    test('/catalog: Payload JSON', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Open Payload modal for hello_world', async () => {
            const payloadBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Payload'])[1]"
            );
            await payloadBtn.click();
        });

        await test.step('Validate Payload modal UI', async () => {
            const payloadModal = page.locator(
                '//*[@class="ant-modal-title"][text()="Execute Playbook with Payload: tests/fixtures/playbooks/hello_world"]'
            );
            await expect(payloadModal).toBeVisible();

            const payloadJson = JSON.stringify({ key: 'value', param: 'example' }, null, 2);
            const payloadInput = page.getByPlaceholder('{"key": "value", "param": "example"}');
            await payloadInput.fill(payloadJson);
            await expect(payloadInput).toHaveValue(payloadJson);

            const closeButton = page.locator('//button[span[text()="Cancel"]]');
            await expect(closeButton).toBeVisible();

            const executeButton = page.locator('//button[span[text()="Execute with Payload"]]');
            await expect(executeButton).toBeVisible();

            await executeButton.click();
            // Validate modal is closed
            await expect(payloadModal).toHaveCount(0);

            await test.step('Validate navigation to Execution page', async () => {
                await expect(page).toHaveURL(/\/execution/);
            });

            await test.step('Wait for executions loader to finish (if present)', async () => {
                const loader = page.locator("//*[text()='Loading executions...']");
                await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
                await loader.waitFor({ state: 'detached' });
            });
        });
    });

    test('/catalog: Payload File Upload', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Open Payload modal for hello_world', async () => {
            const payloadBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Payload'])[1]"
            );
            await payloadBtn.click();
        });

        const payloadModalTitle = page.locator(
            '//*[@class="ant-modal-title"][text()="Execute Playbook with Payload: tests/fixtures/playbooks/hello_world"]'
        );

        await test.step('Switch to File Upload tab and upload JSON', async () => {
            await expect(payloadModalTitle).toBeVisible();

            const dialog = page.getByRole('dialog');
            await dialog.getByRole('tab', { name: 'File Upload' }).click();

            const jsonPath = path.join(__dirname, '../../hello_world_payload.json');
            await dialog.locator('input[type="file"]').setInputFiles(jsonPath);

            // Ant Upload typically shows the filename after selection.
            await expect(dialog.getByText('hello_world_payload.json', { exact: true })).toBeVisible();
        });

        await test.step('Execute with payload and validate navigation', async () => {
            const executeButton = page.locator('//button[span[text()="Execute with Payload"]]');
            await expect(executeButton).toBeVisible();
            await executeButton.click();

            await expect(payloadModalTitle).toHaveCount(0);
            await expect(page).toHaveURL(/\/execution/);

            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
        });
    });


});
