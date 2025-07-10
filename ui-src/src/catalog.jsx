/**
 * @fileoverview Manages the Playbook Catalog page, including listing,
 * executing, and managing playbooks with payloads.
 *
 * This script follows modern best practices by:
 * - Using async/await for cleaner asynchronous code.
 * - Creating DOM elements programmatically to prevent XSS vulnerabilities.
 * - Using event delegation for efficient event handling on dynamic content.
 * - Encapsulating modal logic for better maintainability.
 */

// Import CSS for styling
import '../static/css/main.css';

// --- UTILITY FUNCTIONS ---

/**
 * A simple and safe HTML escaper.
 * @param {string | number | null | undefined} unsafe The string to escape.
 * @returns {string} The escaped string.
 */
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) {
        return '';
    }
    return unsafe
        .toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Displays a dismissible info message at the top of the page.
 * @param {string} message The message to display.
 * @param {'info'|'success'|'warning'|'error'} type The type of message.
 */
function showInfoMessage(message, type = 'info') {
    const infoPanel = document.getElementById('info-panel');
    const infoMessage = document.getElementById('info-message');
    if (!infoPanel || !infoMessage) return;

    infoMessage.innerHTML = ''; // Clear previous content
    infoMessage.appendChild(document.createTextNode(message));

    infoPanel.className = `ant-alert ant-alert-${type} ant-alert-with-description ant-alert-closable`;
    infoPanel.style.display = 'flex'; // Use flex for proper alignment
}

/**
 * Hides the info message panel.
 */
function hideInfoMessage() {
    const infoPanel = document.getElementById('info-panel');
    if (infoPanel) {
        infoPanel.style.display = 'none';
    }
}


// --- API & BUSINESS LOGIC ---

/**
 * Navigates to the playbook view page.
 * @param {string} path The path of the playbook.
 * @param {string} version The version of the playbook.
 */
function viewPlaybook(path, version) {
    window.location.href = `/playbook/${encodeURIComponent(path)}/${encodeURIComponent(version)}`;
}

/**
 * Executes a playbook with a given request body.
 * @param {object} requestBody The body for the /agent/execute request.
 */
async function executePlaybookWithRequestBody(requestBody) {
    showInfoMessage(`Executing playbook "${requestBody.path}"...`, 'info');
    try {
        const response = await fetch('/agent/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown server error.' }));
            throw new Error(errorData.detail || `HTTP error! Status: ${response.status}`);
        }

        const data = await response.json();
        showInfoMessage(`Execution started. ID: ${data.execution_id}`, 'success');

        const infoMessage = document.getElementById('info-message');
        const executionLink = document.createElement('a');
        executionLink.href = `/execution/${data.execution_id}`;
        executionLink.textContent = ' View execution details';
        executionLink.style.color = '#1890ff';
        executionLink.style.textDecoration = 'underline';
        infoMessage.appendChild(executionLink);

    } catch (error) {
        console.error('Error executing playbook:', error);
        showInfoMessage(`Error: ${error.message}`, 'error');
    }
}

/**
 * Fetches playbooks from the catalog and renders them.
 */
async function loadPlaybooks() {
    const playbookList = document.getElementById('playbook-list');
    playbookList.innerHTML = `
        <tr>
            <td colspan="4" style="text-align: center; padding: 24px;">
                <div class="ant-spin ant-spin-spinning"></div>
                <p style="margin-top: 8px;">Loading playbooks...</p>
            </td>
        </tr>`;

    try {
        const response = await fetch('/catalog/list');
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        const data = await response.json();
        renderPlaybookTable(data.entries || []);
    } catch (error) {
        console.error('Error loading playbooks:', error);
        playbookList.innerHTML = `
            <tr class="ant-table-row">
                <td colspan="4" style="text-align: center; color: #f5222d; padding: 24px;">
                    Error loading playbooks. Please check the console and try again later.
                </td>
            </tr>`;
    }
}


// --- DOM RENDERING ---

/**
 * Renders the playbook data into the table.
 * @param {Array<object>} playbooks The list of playbook objects.
 */
function renderPlaybookTable(playbooks) {
    const playbookList = document.getElementById('playbook-list');
    playbookList.innerHTML = ''; // Clear loading indicator or previous content

    if (playbooks.length === 0) {
        const row = playbookList.insertRow();
        row.className = 'ant-table-row';
        const cell = row.insertCell();
        cell.colSpan = 4;
        cell.style.textAlign = 'center';
        cell.style.padding = '24px';
        cell.innerHTML = `No playbooks found. <a href="/editor/new">Create a new playbook</a>`;
        return;
    }

    playbooks.forEach(playbook => {
        const row = playbookList.insertRow();
        row.className = 'ant-table-row';
        row.dataset.path = playbook.resource_path;
        row.dataset.version = playbook.resource_version;

        row.innerHTML = `
            <td class="ant-table-cell">${escapeHtml(playbook.resource_name || 'Unnamed')}</td>
            <td class="ant-table-cell">${escapeHtml(playbook.resource_path)}</td>
            <td class="ant-table-cell">${escapeHtml(playbook.resource_version)}</td>
            <td class="ant-table-cell action-buttons">
                <button class="ant-btn ant-btn-sm ant-btn-primary" data-action="view">View</button>
                <a href="/editor/${encodeURIComponent(playbook.resource_path)}/${encodeURIComponent(playbook.resource_version)}"
                   class="ant-btn ant-btn-sm ant-btn-primary" data-action="edit">Edit</a>
                <button class="ant-btn ant-btn-sm ant-btn-success" data-action="execute">Execute</button>
                <button class="ant-btn ant-btn-sm ant-btn-warning" data-action="payload">Payload</button>
            </td>
        `;
    });
}


// --- PAYLOAD MODAL MANAGEMENT ---

/**
 * Manages the state and interactions of the payload modal.
 */
const payloadModal = {
    element: null,
    path: null,
    version: null,

    init() {
        // This function would create the modal DOM structure once if it doesn't exist.
        // For brevity, we assume the modal HTML is already on the page but hidden.
        this.element = document.getElementById('payload-modal');
        if (!this.element) {
            console.error("Payload modal element not found in the DOM.");
            return;
        }

        // Event listeners for closing the modal
        this.element.querySelector('#modal-cancel').addEventListener('click', () => this.hide());
        this.element.querySelector('#modal-close').addEventListener('click', () => this.hide());

        // Event listener for the final execution
        this.element.querySelector('#execute-with-payload').addEventListener('click', () => this.execute());

        // File input listener
        const fileInput = this.element.querySelector('#payload-file');
        const fileNameDisplay = this.element.querySelector('#file-name-display');
        fileInput.addEventListener('change', () => {
            fileNameDisplay.textContent = fileInput.files.length > 0 ? `Selected: ${fileInput.files[0].name}` : '';
        });

        // Tab listeners
        this.setupTabs();
    },

    setupTabs() {
        const tabsContainer = this.element.querySelector('#payloadTabs');
        tabsContainer.addEventListener('click', (e) => {
            const tabButton = e.target.closest('.ant-tabs-tab-btn');
            if (!tabButton) return;

            const targetId = tabButton.dataset.tabId;
            tabsContainer.querySelectorAll('.ant-tabs-tab').forEach(t => t.classList.remove('ant-tabs-tab-active'));
            tabsContainer.querySelectorAll('.ant-tabs-tabpane').forEach(p => p.style.display = 'none');

            tabButton.closest('.ant-tabs-tab').classList.add('ant-tabs-tab-active');
            document.getElementById(targetId).style.display = 'block';
        });
    },

    show(path, version) {
        if (!this.element) return;
        this.path = path;
        this.version = version;

        // Reset form fields
        this.element.querySelector('#payload-json').value = '';
        this.element.querySelector('#payload-file').value = '';
        this.element.querySelector('#file-name-display').textContent = '';
        this.element.querySelector('#merge-payload').checked = false;

        this.element.style.display = 'block';
    },

    hide() {
        if (this.element) {
            this.element.style.display = 'none';
        }
    },

    async execute() {
        const mergePayload = this.element.querySelector('#merge-payload').checked;
        let payloadObject = null;

        const activeTab = this.element.querySelector('.ant-tabs-tab-active .ant-tabs-tab-btn');
        const isJsonTab = activeTab.dataset.tabId === 'json-content';
        const isFileTab = activeTab.dataset.tabId === 'file-upload';

        try {
            if (isJsonTab) {
                const jsonText = this.element.querySelector('#payload-json').value.trim();
                if (jsonText) {
                    payloadObject = JSON.parse(jsonText);
                }
            } else if (isFileTab) {
                const fileInput = this.element.querySelector('#payload-file');
                if (fileInput.files.length > 0) {
                    const file = fileInput.files[0];
                    const fileText = await file.text();
                    payloadObject = JSON.parse(fileText);
                }
            }
        } catch (e) {
            // Use the info panel instead of alert for consistent UI
            showInfoMessage('Invalid JSON format. Please check your input.', 'error');
            return;
        }

        const requestBody = {
            path: this.path,
            version: this.version,
            sync_to_postgres: true,
            merge: mergePayload,
        };

        if (payloadObject) {
            requestBody.input_payload = payloadObject;
        }

        this.hide();
        executePlaybookWithRequestBody(requestBody);
    }
};


// --- INITIALIZATION ---

document.addEventListener('DOMContentLoaded', function() {
    // Initialize components
    loadPlaybooks();
    payloadModal.init();

    // Setup event listeners
    document.querySelector('#info-panel .ant-alert-close-icon')?.addEventListener('click', hideInfoMessage);

    // Use event delegation for the playbook list
    document.getElementById('playbook-list').addEventListener('click', (e) => {
        const button = e.target.closest('button[data-action]');
        if (!button) return;

        const row = button.closest('tr');
        const path = row.dataset.path;
        const version = row.dataset.version;
        const action = button.dataset.action;

        if (action === 'view') {
            viewPlaybook(path, version);
        } else if (action === 'execute') {
            executePlaybookWithRequestBody({ path, version, sync_to_postgres: true });
        } else if (action === 'payload') {
            payloadModal.show(path, version);
        }
    });
});
