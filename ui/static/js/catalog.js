document.addEventListener('DOMContentLoaded', function() {
    loadPlaybooks();

    document.querySelector('#info-panel .btn-close').addEventListener('click', function() {
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
                <tr>
                    <td colspan="4" class="text-center text-danger">
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
            <tr>
                <td colspan="4" class="text-center">
                    No playbooks found. <a href="/editor/new">Create a new playbook</a>
                </td>
            </tr>
        `;
        return;
    }

    let html = '';

    playbooks.forEach(playbook => {
        html += `
            <tr>
                <td>${escapeHtml(playbook.resource_name || 'Unnamed')}</td>
                <td>${escapeHtml(playbook.resource_path)}</td>
                <td>${escapeHtml(playbook.resource_version)}</td>
                <td class="action-buttons">
                    <a href="/editor/${encodeURIComponent(playbook.resource_path)}/${encodeURIComponent(playbook.resource_version)}" 
                       class="btn btn-sm btn-primary">Edit</a>
                    <button class="btn btn-sm btn-success" 
                            onclick="executePlaybook('${escapeHtml(playbook.resource_path)}', '${escapeHtml(playbook.resource_version)}')">
                        Execute
                    </button>
                    <button class="btn btn-sm btn-info" 
                            onclick="viewPlaybook('${escapeHtml(playbook.resource_path)}', '${escapeHtml(playbook.resource_version)}')">
                        View
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

    infoPanel.className = `alert alert-${type} alert-dismissible fade show mb-3`;

    infoPanel.classList.remove('d-none');
}

function hideInfoMessage() {
    const infoPanel = document.getElementById('info-panel');
    infoPanel.classList.add('d-none');
}

function executePlaybook(path, version) {
    showInfoMessage(`Executing playbook "${path}" version "${version}"...`, 'info');

    fetch('/agent/execute', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            path: path,
            version: version,
            sync_to_postgres: true
        }),
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
        executionLink.className = 'alert-link';
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
