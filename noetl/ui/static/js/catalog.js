document.addEventListener('DOMContentLoaded', function() {
    loadPlaybooks();

    document.querySelector('#info-panel .ant-alert-close-icon').addEventListener('click', function() {
        hideInfoMessage();
    });
});

function loadPlaybooks() {
    fetch('/catalog/list')
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            displayPlaybooks(data.entries || []);
        })
        .catch(error => {
            console.error('Error loading playbooks:', error);
            document.getElementById('playbook-list').innerHTML = `
                <tr class="ant-table-row">
                    <td colspan="4" style="text-align: center; color: #f5222d;">
                        Error loading playbooks. Please try again later.
                    </td>
                </tr>
            `;
        });
}


function displayPlaybooks(playbooks) {
    const playbookList = document.getElementById('playbook-list');

    if (playbooks.length === 0) {
        playbookList.innerHTML = `
            <tr class="ant-table-row">
                <td colspan="4" style="text-align: center;">
                    No playbooks found. <a href="/editor/new">Create a new playbook</a>
                </td>
            </tr>
        `;
        return;
    }

    let html = '';

    playbooks.forEach(playbook => {
        html += `
            <tr class="ant-table-row">
                <td class="ant-table-cell">${escapeHtml(playbook.resource_name || 'Unnamed')}</td>
                <td class="ant-table-cell">${escapeHtml(playbook.resource_path)}</td>
                <td class="ant-table-cell">${escapeHtml(playbook.resource_version)}</td>
                <td class="ant-table-cell action-buttons">
                    <button class="ant-btn ant-btn-sm" style="background-color: #1890ff; color: white; margin-right: 4px; height: 24px; padding: 0 7px; border: 1px solid #1890ff;"
                            onclick="viewPlaybook('${escapeHtml(playbook.resource_path)}', '${escapeHtml(playbook.resource_version)}')">
                        View
                    </button>
                    <a href="/editor/${encodeURIComponent(playbook.resource_path)}/${encodeURIComponent(playbook.resource_version)}" 
                       class="ant-btn ant-btn-sm" style="background-color: #1890ff; color: white; margin-right: 4px; height: 24px; padding: 0 7px; border: 1px solid #1890ff; display: inline-flex; align-items: center;">Edit</a>
                    <button class="ant-btn ant-btn-sm" style="background-color: #52c41a; color: white; margin-right: 4px; height: 24px; padding: 0 7px; border: 1px solid #52c41a;"
                            onclick="executePlaybook('${escapeHtml(playbook.resource_path)}', '${escapeHtml(playbook.resource_version)}')">
                        Execute
                    </button>
                    <button class="ant-btn ant-btn-sm" style="background-color: #faad14; color: white; height: 24px; padding: 0 7px; border: 1px solid #faad14;"
                            onclick="console.log('Payload button clicked'); showPayloadModal('${escapeHtml(playbook.resource_path)}', '${escapeHtml(playbook.resource_version)}')">
                        Payload
                    </button>
                </td>
            </tr>
        `;
    });

    playbookList.innerHTML = html;
}


function showInfoMessage(message, type = 'info') {
    const infoPanel = document.getElementById('info-panel');
    const infoMessage = document.getElementById('info-message');

    infoMessage.textContent = message;

    // Map Bootstrap alert types to Ant Design alert types
    const typeMap = {
        'info': 'info',
        'success': 'success',
        'warning': 'warning',
        'danger': 'error'
    };

    const antType = typeMap[type] || 'info';
    infoPanel.className = `ant-alert ant-alert-${antType} ant-alert-with-description ant-alert-closable`;
    infoPanel.style.display = 'block';
}

function hideInfoMessage() {
    const infoPanel = document.getElementById('info-panel');
    infoPanel.style.display = 'none';
}

function executePlaybook(path, version, payload = null) {
    showInfoMessage(`Executing playbook "${path}" version "${version}"...`, 'info');

    const requestBody = {
        path: path,
        version: version,
        sync_to_postgres: true
    };

    if (payload) {
        requestBody.input_payload = payload;
    }

    fetch('/agent/execute', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        showInfoMessage(`Playbook execution started. Execution ID: ${data.execution_id}`, 'success');
        const infoMessage = document.getElementById('info-message');
        const executionLink = document.createElement('a');
        executionLink.href = `/execution/${data.execution_id}`;
        executionLink.textContent = ' View execution details';
        executionLink.style.color = '#1890ff';
        executionLink.style.textDecoration = 'underline';
        infoMessage.appendChild(executionLink);
    })
    .catch(error => {
        console.error('Error executing playbook:', error);
        showInfoMessage('Error executing playbook. Please try again later.', 'danger');
    });
}


function viewPlaybook(path, version) {
    window.location.href = `/playbook/${encodeURIComponent(path)}/${encodeURIComponent(version)}`;
}


function showPayloadModal(path, version) {
    console.log("showPayloadModal called with path:", path, "version:", version);
    // Create modal if it doesn't exist
    if (!document.getElementById('payload-modal')) {
        console.log("Creating payload modal");
        const modalHtml = `
            <div class="ant-modal-root" id="payload-modal" style="display: none; position: fixed; inset: 0; z-index: 1000;">
                <div class="ant-modal-mask" style="background-color: rgba(0, 0, 0, 0.45); position: fixed; inset: 0; z-index: 1000;"></div>
                <div class="ant-modal-wrap" style="position: fixed; top: 0; right: 0; bottom: 0; left: 0; overflow: auto; outline: 0; -webkit-overflow-scrolling: touch; display: flex; align-items: center; justify-content: center; z-index: 1001;">
                    <div class="ant-modal" style="width: 800px; position: relative; top: 0; margin: 0 auto; z-index: 1001;">
                        <div class="ant-modal-content" style="background-color: white; border-radius: 12px; box-shadow: 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 9px 28px 8px rgba(0, 0, 0, 0.05);">
                            <div class="ant-modal-header" style="border-radius: 12px 12px 0 0; background: linear-gradient(to right, #fafafa, #f5f5f5); padding: 16px 24px;">
                                <div class="ant-modal-title" id="payloadModalLabel" style="font-size: 18px; font-weight: 600; color: rgba(0, 0, 0, 0.85);">
                                    <i class="fas fa-code" style="margin-right: 10px; color: #1890ff;"></i>Add Payload
                                </div>
                            </div>
                            <button type="button" class="ant-modal-close" id="modal-close" aria-label="Close" style="color: rgba(0, 0, 0, 0.45); transition: color 0.3s;">
                                <span class="ant-modal-close-x" style="width: 54px; height: 54px; line-height: 54px;">
                                    <span class="anticon anticon-close"><i class="fas fa-times"></i></span>
                                </span>
                            </button>
                            <div class="ant-modal-body" style="padding: 24px;">
                                <div class="ant-tabs ant-tabs-top" id="payloadTabs">
                                    <div class="ant-tabs-nav" style="margin-bottom: 16px; border-bottom: 1px solid #f0f0f0;">
                                        <div class="ant-tabs-nav-list" style="display: flex;">
                                            <div class="ant-tabs-tab ant-tabs-tab-active" id="json-tab" style="margin-right: 8px; padding: 8px 16px; border: 1px solid #f0f0f0; border-bottom: none; border-radius: 4px 4px 0 0; background-color: white; position: relative; bottom: -1px;">
                                                <div class="ant-tabs-tab-btn" role="tab" aria-selected="true" data-tab-id="json-content" style="font-weight: 500;">JSON</div>
                                            </div>
                                            <div class="ant-tabs-tab" id="file-tab" style="padding: 8px 16px; border: 1px solid #f0f0f0; border-bottom: none; border-radius: 4px 4px 0 0; background-color: #f5f5f5;">
                                                <div class="ant-tabs-tab-btn" role="tab" aria-selected="false" data-tab-id="file-content" style="font-weight: 500;">File Upload</div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="ant-tabs-content">
                                        <div class="ant-tabs-tabpane ant-tabs-tabpane-active" id="json-content" role="tabpanel" aria-labelledby="json-tab">
                                            <div class="ant-form-item" style="margin-top: 16px;">
                                                <label for="payload-json" class="ant-form-item-label" style="font-weight: 500; margin-bottom: 8px;">
                                                    <i class="fas fa-code" style="margin-right: 8px; color: #1890ff;"></i>JSON Payload
                                                </label>
                                                <div class="ant-form-item-control">
                                                    <div class="ant-form-item-control-input">
                                                        <textarea class="ant-input" id="payload-json" rows="10" placeholder='{"key": "value"}' style="resize: vertical; border-radius: 8px; padding: 12px; box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.05); border: 1px solid #1890ff;"></textarea>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="ant-tabs-tabpane" id="file-content" role="tabpanel" aria-labelledby="file-tab" style="display: none;">
                                            <div class="ant-form-item" style="margin-top: 16px;">
                                                <label for="payload-file" class="ant-form-item-label" style="font-weight: 500; margin-bottom: 8px;">
                                                    <i class="fas fa-upload" style="margin-right: 8px; color: #1890ff;"></i>Upload JSON File
                                                </label>
                                                <div class="ant-form-item-control">
                                                    <div class="ant-form-item-control-input">
                                                        <div class="ant-upload ant-upload-select">
                                                            <div class="ant-upload ant-upload-select-text">
                                                                <input type="file" id="payload-file" accept=".json" style="display: none;">
                                                                <button type="button" class="ant-btn" onclick="document.getElementById('payload-file').click()" style="height: 40px; padding: 0 16px; border: 1px solid #1890ff; display: flex; align-items: center; justify-content: center; border-radius: 6px;">
                                                                    <i class="fas fa-upload" style="margin-right: 8px;"></i>
                                                                    <span>Click to Upload</span>
                                                                </button>
                                                                <div id="file-name-display" style="margin-top: 8px; color: rgba(0, 0, 0, 0.65);"></div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="ant-checkbox-wrapper" style="margin-top: 16px;">
                                    <span class="ant-checkbox">
                                        <input type="checkbox" class="ant-checkbox-input" id="merge-payload">
                                        <span class="ant-checkbox-inner"></span>
                                    </span>
                                    <span>Merge with existing workload (instead of replacing)</span>
                                </div>
                            </div>
                            <div class="ant-modal-footer" style="border-top: 1px solid #f0f0f0; padding: 16px 24px; border-radius: 0 0 12px 12px; display: flex; justify-content: flex-end;">
                                <button type="button" class="ant-btn" id="modal-cancel" style="margin-right: 12px; height: 38px; padding: 0 16px; border-radius: 6px; display: flex; align-items: center; justify-content: center;">
                                    <i class="fas fa-times" style="margin-right: 8px;"></i>Cancel
                                </button>
                                <button type="button" class="ant-btn ant-btn-primary" id="execute-with-payload" style="height: 38px; padding: 0 16px; background: linear-gradient(to right, #1890ff, #096dd9); border: none; border-radius: 6px; display: flex; align-items: center; justify-content: center;">
                                    <i class="fas fa-check" style="margin-right: 8px;"></i>Execute with Payload
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Add event listener to the execute button
        document.getElementById('execute-with-payload').addEventListener('click', function() {
            executeWithPayload();
        });

        // Add event listener to the close button
        document.getElementById('modal-close').addEventListener('click', function() {
            hidePayloadModal();
        });

        // Add event listener to the cancel button
        document.getElementById('modal-cancel').addEventListener('click', function() {
            hidePayloadModal();
        });

        // Setup tabs
        const jsonTab = document.getElementById('json-tab');
        const fileTab = document.getElementById('file-tab');
        const jsonContent = document.getElementById('json-content');
        const fileContent = document.getElementById('file-content');

        jsonTab.addEventListener('click', function() {
            // Update tab classes
            jsonTab.classList.add('ant-tabs-tab-active');
            fileTab.classList.remove('ant-tabs-tab-active');

            // Update tab styles
            jsonTab.style.backgroundColor = 'white';
            jsonTab.style.position = 'relative';
            jsonTab.style.bottom = '-1px';
            fileTab.style.backgroundColor = '#f5f5f5';
            fileTab.style.position = '';
            fileTab.style.bottom = '';

            // Show/hide content
            jsonContent.style.display = 'block';
            fileContent.style.display = 'none';
        });

        fileTab.addEventListener('click', function() {
            // Update tab classes
            fileTab.classList.add('ant-tabs-tab-active');
            jsonTab.classList.remove('ant-tabs-tab-active');

            // Update tab styles
            fileTab.style.backgroundColor = 'white';
            fileTab.style.position = 'relative';
            fileTab.style.bottom = '-1px';
            jsonTab.style.backgroundColor = '#f5f5f5';
            jsonTab.style.position = '';
            jsonTab.style.bottom = '';

            // Show/hide content
            fileContent.style.display = 'block';
            jsonContent.style.display = 'none';
        });

        // Add event listener to file input to display selected file name
        const fileInput = document.getElementById('payload-file');
        const fileNameDisplay = document.getElementById('file-name-display');

        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                fileNameDisplay.textContent = `Selected file: ${this.files[0].name}`;
            } else {
                fileNameDisplay.textContent = '';
            }
        });
    }

    // Store the current playbook path and version
    document.getElementById('payload-modal').setAttribute('data-path', path);
    document.getElementById('payload-modal').setAttribute('data-version', version);

    // Clear previous values
    document.getElementById('payload-json').value = '';
    document.getElementById('payload-file').value = '';
    document.getElementById('file-name-display').textContent = '';
    document.getElementById('merge-payload').checked = false;

    // Show the modal
    const modalElement = document.getElementById('payload-modal');
    if (modalElement) {
        console.log("Showing payload modal");
        modalElement.style.display = 'block';
        console.log("Modal display style set to:", modalElement.style.display);
    } else {
        console.error("Payload modal element not found when trying to show it");
    }
}

function hidePayloadModal() {
    console.log("hidePayloadModal called");
    const modal = document.getElementById('payload-modal');
    if (modal) {
        console.log("Hiding payload modal");
        modal.style.display = 'none';
    } else {
        console.error("Payload modal not found");
    }
}

function executeWithPayload() {
    const modal = document.getElementById('payload-modal');
    const path = modal.getAttribute('data-path');
    const version = modal.getAttribute('data-version');
    const mergePayload = document.getElementById('merge-payload').checked;

    let payload = null;

    // Get payload from JSON textarea or file upload
    if (document.getElementById('json-tab').classList.contains('ant-tabs-tab-active')) {
        try {
            const jsonText = document.getElementById('payload-json').value.trim();
            if (jsonText) {
                payload = JSON.parse(jsonText);
            }
        } catch (e) {
            showInfoMessage('Invalid JSON payload. Please check the format.', 'danger');
            return;
        }
    } else {
        const fileInput = document.getElementById('payload-file');
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            const reader = new FileReader();

            reader.onload = function(e) {
                try {
                    payload = JSON.parse(e.target.result);

                    // Execute with the payload from the file
                    const requestBody = {
                        path: path,
                        version: version,
                        input_payload: payload,
                        sync_to_postgres: true,
                        merge: mergePayload
                    };

                    // Hide the modal
                    hidePayloadModal();

                    // Execute the playbook with the payload
                    executePlaybookWithRequestBody(requestBody);

                } catch (e) {
                    showInfoMessage('Invalid JSON file. Please check the format.', 'danger');
                }
            };

            reader.readAsText(file);
            return; // Return early as we're handling this asynchronously
        }
    }

    // If we got here with the JSON tab, execute with the payload
    if (payload || document.getElementById('json-tab').classList.contains('ant-tabs-tab-active')) {
        const requestBody = {
            path: path,
            version: version,
            sync_to_postgres: true,
            merge: mergePayload
        };

        if (payload) {
            requestBody.input_payload = payload;
        }

        // Hide the modal
        hidePayloadModal();

        // Execute the playbook with the payload
        executePlaybookWithRequestBody(requestBody);
    }
}

function executePlaybookWithRequestBody(requestBody) {
    showInfoMessage(`Executing playbook "${requestBody.path}" version "${requestBody.version}"...`, 'info');

    fetch('/agent/execute', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        showInfoMessage(`Playbook execution started. Execution ID: ${data.execution_id}`, 'success');
        const infoMessage = document.getElementById('info-message');
        const executionLink = document.createElement('a');
        executionLink.href = `/execution/${data.execution_id}`;
        executionLink.textContent = ' View execution details';
        executionLink.style.color = '#1890ff';
        executionLink.style.textDecoration = 'underline';
        infoMessage.appendChild(executionLink);
    })
    .catch(error => {
        console.error('Error executing playbook:', error);
        showInfoMessage('Error executing playbook. Please try again later.', 'danger');
    });
}

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
