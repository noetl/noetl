let executionId = null;
let refreshInterval = null;
const REFRESH_INTERVAL_MS = 5000;

document.addEventListener('DOMContentLoaded', function() {
    const pathParts = window.location.pathname.split('/');
    if (pathParts.length >= 3 && pathParts[1] === 'execution') {
        executionId = decodeURIComponent(pathParts[2]);
        document.getElementById('execution-title').textContent = `Execution: ${executionId}`;
        document.getElementById('execution-id').textContent = executionId;
        loadExecutionData();
        refreshInterval = setInterval(loadExecutionData, REFRESH_INTERVAL_MS);
    } else {
        showError('No execution ID provided.');
    }

    document.getElementById('refresh-execution').addEventListener('click', loadExecutionData);
    document.getElementById('back-to-catalog').addEventListener('click', () => {
        window.location.href = '/';
    });
});

function loadExecutionData() {
    if (!executionId) return;

    fetch(`/execution/data/${encodeURIComponent(executionId)}`)
        .then(response => {
            if (!response.ok) {
                // Fallback to the old endpoint for backward compatibility
                return fetch(`/events/query?event_id=${encodeURIComponent(executionId)}`);
            }
            return response;
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            displayExecutionData(data);
        })
        .catch(error => {
            console.error('Error loading execution data:', error);
            showError('Error loading execution data. Please try again later.');
        });
}

function displayExecutionData(data) {
    if (!data || !data.events || data.events.length === 0) {
        showError('No execution data found.');
        return;
    }
    const events = data.events;
    const executionEvent = events.find(event => event.event_type === 'execution_start');
    if (!executionEvent) {
        showError('No execution start event found.');
        return;
    }

    const executionEndEvent = events.find(event => event.event_type === 'execution_end' || event.event_type === 'execution_complete');
    document.getElementById('playbook-path').textContent = executionEvent.resource_path || 'Unknown';
    document.getElementById('playbook-version').textContent = executionEvent.resource_version || 'Unknown';

    const startTime = new Date(executionEvent.timestamp);
    document.getElementById('start-time').textContent = moment(startTime).format('YYYY-MM-DD HH:mm:ss');

    if (executionEndEvent) {
        const endTime = new Date(executionEndEvent.timestamp);
        document.getElementById('end-time').textContent = moment(endTime).format('YYYY-MM-DD HH:mm:ss');

        const duration = moment.duration(endTime - startTime);
        document.getElementById('duration').textContent = formatDuration(duration);
    } else {
        document.getElementById('end-time').textContent = 'Still running...';

        const duration = moment.duration(moment() - startTime);
        document.getElementById('duration').textContent = formatDuration(duration) + ' (running)';
    }

    updateExecutionStatus(events);

    updateExecutionSteps(events);

    updateExecutionResults(events);

    if (executionEndEvent) {
        clearInterval(refreshInterval);
    }
}


function updateExecutionStatus(events) {
    const statusContainer = document.getElementById('execution-status');
    const statusText = document.getElementById('status-text');
    const statusDetails = document.getElementById('status-details');
    const spinner = document.getElementById('execution-spinner');

    const executionEndEvent = events.find(event => event.event_type === 'execution_end' || event.event_type === 'execution_complete');

    if (executionEndEvent) {
        spinner.style.display = 'none';

        if (executionEndEvent.status === 'success') {
            statusContainer.className = 'execution-status status-success';
            statusText.textContent = 'Execution completed successfully';
            statusDetails.textContent = executionEndEvent.message || '';
        } else {
            statusContainer.className = 'execution-status status-error';
            statusText.textContent = 'Execution failed';
            statusDetails.textContent = executionEndEvent.error || executionEndEvent.message || '';
        }
    } else {
        statusContainer.className = 'execution-status status-running';
        statusText.textContent = 'Execution in progress...';

        const latestEvent = events.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
        statusDetails.textContent = latestEvent.message || '';
    }
}


function updateExecutionSteps(events) {
    const stepsContainer = document.getElementById('steps-container');
    const template = document.getElementById('execution-steps-template');

    const stepEvents = events.filter(event => 
        event.event_type === 'step_start' || 
        event.event_type === 'step_end' ||
        event.event_type === 'step_complete'
    );

    if (stepEvents.length === 0) {
        stepsContainer.innerHTML = '<div class="ant-alert ant-alert-info" style="margin-bottom: 16px;"><span class="ant-alert-message">No step events found.</span></div>';
        return;
    }

    const stepsByName = {};
    stepEvents.forEach(event => {
        const stepName = event.node_name || event.step_name || 'unknown';
        if (!stepsByName[stepName]) {
            stepsByName[stepName] = [];
        }
        stepsByName[stepName].push(event);
    });

    // Clone the template content
    const templateContent = template.content.cloneNode(true);
    const listGroup = templateContent.querySelector('.ant-list');
    const stepItemTemplate = listGroup.querySelector('.ant-list-item');

    // Remove the template item from the list group
    listGroup.innerHTML = '';

    Object.keys(stepsByName).forEach(stepName => {
        const stepEventsForName = stepsByName[stepName];

        const startEvent = stepEventsForName.find(event => event.event_type === 'step_start');
        const endEvent = stepEventsForName.find(event => event.event_type === 'step_end' || event.event_type === 'step_complete');

        let statusClass = 'step-running';
        let statusIcon = '<i class="fas fa-spinner fa-spin" style="margin-right: 8px;"></i>';
        let statusText = 'Running';

        if (endEvent) {
            if (endEvent.status === 'success') {
                statusClass = 'step-success';
                statusIcon = '<i class="fas fa-check-circle" style="margin-right: 8px;"></i>';
                statusText = 'Success';
            } else {
                statusClass = 'step-error';
                statusIcon = '<i class="fas fa-times-circle" style="margin-right: 8px;"></i>';
                statusText = 'Failed';
            }
        }

        // Clone the step item template
        const stepItem = stepItemTemplate.cloneNode(true);

        // Add the status class
        stepItem.classList.add(statusClass);

        // Set the step name and status icon
        const nameElement = stepItem.querySelector('strong');
        nameElement.textContent = stepName;
        nameElement.parentNode.innerHTML = statusIcon + ' ' + nameElement.outerHTML;

        // Set the status badge
        const statusBadge = stepItem.querySelector('.ant-tag');
        statusBadge.textContent = statusText;

        // Set the start and end times
        const timeInfo = stepItem.querySelector('[style="margin-top: 12px; color: rgba(0, 0, 0, 0.65);"]');
        timeInfo.innerHTML = `
            <small style="display: block; margin-bottom: 4px;">
                <i class="fas fa-clock" style="margin-right: 8px;"></i>Started: ${startEvent ? moment(new Date(startEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss') : 'Unknown'}
            </small>
            ${endEvent ? `
                <small style="display: block;">
                    <i class="fas fa-flag-checkered" style="margin-right: 8px;"></i>Ended: ${moment(new Date(endEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss')}
                </small>
            ` : ''}
        `;

        // Set the error message if any
        const errorDiv = stepItem.querySelector('[style="margin-top: 12px; color: #f5222d; background-color: #fff1f0; padding: 8px 12px; border-radius: 4px; border-left: 4px solid #ff4d4f;"]');
        if (endEvent && endEvent.status !== 'success') {
            errorDiv.textContent = endEvent.error || 'Unknown error';
        } else {
            errorDiv.style.display = 'none';
        }

        // Add the step item to the list group
        listGroup.appendChild(stepItem);
    });

    // Clear the container and add the new content
    stepsContainer.innerHTML = '';
    stepsContainer.appendChild(templateContent);
}

function updateExecutionResults(events) {
    const resultsContainer = document.getElementById('results-container');

    const executionEndEvent = events.find(event => event.event_type === 'execution_end' || event.event_type === 'execution_complete');

    if (!executionEndEvent) {
        resultsContainer.innerHTML = '<div class="ant-alert ant-alert-info" style="margin-bottom: 16px; border-radius: 4px; padding: 8px 15px;"><span class="ant-alert-message">Execution is still running. Results will be available when execution completes.</span></div>';
        return;
    }

    const results = executionEndEvent.results || {};

    if (Object.keys(results).length === 0) {
        resultsContainer.innerHTML = '<div class="ant-alert ant-alert-info" style="margin-bottom: 16px; border-radius: 4px; padding: 8px 15px;"><span class="ant-alert-message">No results available.</span></div>';
        return;
    }

    let html = '<div class="ant-collapse" style="background: #fff; border-radius: 4px;">';

    Object.keys(results).forEach((key, index) => {
        const value = results[key];
        let contentHtml = '';

        // Check if this is a transition table (based on content format)
        if (key.toLowerCase().includes('transition') || 
            (typeof value === 'string' && value.includes('execution_id,from_step,to_step'))) {

            // Parse the CSV-like transition data
            const lines = value.toString().trim().split('\n');
            if (lines.length > 0) {
                const headers = lines[0].split(',');

                // Create a proper HTML table using Ant Design table classes
                contentHtml = `
                    <div style="overflow-x: auto;">
                        <table class="ant-table" style="width: 100%; border-collapse: collapse;">
                            <thead class="ant-table-thead">
                                <tr>
                                    ${headers.map(header => `<th class="ant-table-cell" style="background-color: #fafafa; padding: 16px; font-weight: 600; border-bottom: 1px solid #f0f0f0;">${escapeHtml(header)}</th>`).join('')}
                                </tr>
                            </thead>
                            <tbody class="ant-table-tbody">
                `;

                // Add data rows
                for (let i = 1; i < lines.length; i++) {
                    const cells = lines[i].split(',');
                    contentHtml += '<tr class="ant-table-row">';
                    for (let j = 0; j < cells.length; j++) {
                        contentHtml += `<td class="ant-table-cell" style="padding: 16px; border-bottom: 1px solid #f0f0f0;">${escapeHtml(cells[j])}</td>`;
                    }
                    contentHtml += '</tr>';
                }

                contentHtml += `
                            </tbody>
                        </table>
                    </div>
                `;
            }
        } else {
            // Default display for non-transition data
            const valueStr = typeof value === 'object' ? JSON.stringify(value, null, 2) : value.toString();
            contentHtml = `<pre style="margin: 0; padding: 16px; background-color: #f5f5f5; border-radius: 4px; overflow: auto;"><code>${escapeHtml(valueStr)}</code></pre>`;
        }

        // Use Ant Design collapse panel
        const isActive = index === 0 ? 'ant-collapse-item-active' : '';
        html += `
            <div class="ant-collapse-item ${isActive}" style="border-bottom: 1px solid #d9d9d9;">
                <div class="ant-collapse-header" style="padding: 12px 16px; cursor: pointer; display: flex; align-items: center;" onclick="toggleCollapsePanel(this)">
                    <i class="ant-collapse-arrow" style="margin-right: 12px; transition: transform 0.3s; ${index === 0 ? 'transform: rotate(90deg);' : ''}">
                        <svg viewBox="64 64 896 896" focusable="false" data-icon="right" width="12px" height="12px" fill="currentColor" aria-hidden="true">
                            <path d="M765.7 486.8L314.9 134.7A7.97 7.97 0 00302 141v77.3c0 4.9 2.3 9.6 6.1 12.6l360 281.1-360 281.1c-3.9 3-6.1 7.7-6.1 12.6V883c0 6.7 7.7 10.4 12.9 6.3l450.8-352.1a31.96 31.96 0 000-50.4z"></path>
                        </svg>
                    </i>
                    <span style="font-weight: 500;">${escapeHtml(key)}</span>
                </div>
                <div class="ant-collapse-content ${index === 0 ? 'ant-collapse-content-active' : 'ant-collapse-content-inactive'}" style="${index === 0 ? '' : 'display: none;'} border-top: 1px solid #d9d9d9;">
                    <div class="ant-collapse-content-box" style="padding: 16px;">
                        ${contentHtml}
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';

    // Add the toggle function for collapse panels
    html += `
    <script>
    function toggleCollapsePanel(header) {
        const item = header.parentNode;
        const content = item.querySelector('.ant-collapse-content');
        const arrow = header.querySelector('.ant-collapse-arrow');

        if (content.classList.contains('ant-collapse-content-active')) {
            content.classList.remove('ant-collapse-content-active');
            content.classList.add('ant-collapse-content-inactive');
            content.style.display = 'none';
            arrow.style.transform = '';
        } else {
            content.classList.add('ant-collapse-content-active');
            content.classList.remove('ant-collapse-content-inactive');
            content.style.display = 'block';
            arrow.style.transform = 'rotate(90deg)';
        }
    }
    </script>
    `;
    resultsContainer.innerHTML = html;
}

function showError(message) {
    const statusContainer = document.getElementById('execution-status');
    const statusText = document.getElementById('status-text');
    const statusDetails = document.getElementById('status-details');
    const spinner = document.getElementById('execution-spinner');

    statusContainer.className = 'execution-status status-error';
    statusText.textContent = 'Error';
    statusDetails.textContent = message;
    spinner.style.display = 'none';

    document.getElementById('steps-container').innerHTML = '<div class="ant-alert ant-alert-error" style="margin-bottom: 16px; border-radius: 4px; padding: 8px 15px;"><span class="ant-alert-message">Error: ' + escapeHtml(message) + '</span></div>';
    document.getElementById('results-container').innerHTML = '<div class="ant-alert ant-alert-error" style="margin-bottom: 16px; border-radius: 4px; padding: 8px 15px;"><span class="ant-alert-message">Error: ' + escapeHtml(message) + '</span></div>';
}

function formatDuration(duration) {
    const hours = Math.floor(duration.asHours());
    const minutes = duration.minutes();
    const seconds = duration.seconds();

    let result = '';
    if (hours > 0) {
        result += hours + 'h ';
    }
    if (minutes > 0 || hours > 0) {
        result += minutes + 'm ';
    }
    result += seconds + 's';

    return result;
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
