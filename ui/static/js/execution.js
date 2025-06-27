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

    fetch(`/events/query?event_id=${encodeURIComponent(executionId)}`)
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

    const executionEndEvent = events.find(event => event.event_type === 'execution_end');
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

    const executionEndEvent = events.find(event => event.event_type === 'execution_end');

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

    const stepEvents = events.filter(event => 
        event.event_type === 'step_start' || 
        event.event_type === 'step_end'
    );

    if (stepEvents.length === 0) {
        stepsContainer.innerHTML = '<div class="alert alert-info">No step events found.</div>';
        return;
    }

    const stepsByName = {};
    stepEvents.forEach(event => {
        const stepName = event.step_name || 'unknown';
        if (!stepsByName[stepName]) {
            stepsByName[stepName] = [];
        }
        stepsByName[stepName].push(event);
    });

    let html = '<div class="list-group">';

    Object.keys(stepsByName).forEach(stepName => {
        const stepEventsForName = stepsByName[stepName];

        const startEvent = stepEventsForName.find(event => event.event_type === 'step_start');
        const endEvent = stepEventsForName.find(event => event.event_type === 'step_end');

        let statusClass = 'step-running';
        let statusIcon = '<i class="fas fa-spinner fa-spin me-2"></i>';
        let statusText = 'Running';

        if (endEvent) {
            if (endEvent.status === 'success') {
                statusClass = 'step-success';
                statusIcon = '<i class="fas fa-check-circle me-2"></i>';
                statusText = 'Success';
            } else {
                statusClass = 'step-error';
                statusIcon = '<i class="fas fa-times-circle me-2"></i>';
                statusText = 'Failed';
            }
        }

        html += `
            <div class="list-group-item step-status ${statusClass}">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        ${statusIcon} <strong>${escapeHtml(stepName)}</strong>
                    </div>
                    <span class="badge bg-secondary">${statusText}</span>
                </div>
                <div class="mt-2">
                    <small>
                        Started: ${startEvent ? moment(new Date(startEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss') : 'Unknown'}
                    </small>
                    ${endEvent ? `
                        <br>
                        <small>
                            Ended: ${moment(new Date(endEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss')}
                        </small>
                    ` : ''}
                </div>
                ${endEvent && endEvent.status !== 'success' ? `
                    <div class="mt-2 text-danger">
                        ${escapeHtml(endEvent.error || 'Unknown error')}
                    </div>
                ` : ''}
            </div>
        `;
    });

    html += '</div>';
    stepsContainer.innerHTML = html;
}

function updateExecutionResults(events) {
    const resultsContainer = document.getElementById('results-container');

    const executionEndEvent = events.find(event => event.event_type === 'execution_end');

    if (!executionEndEvent) {
        resultsContainer.innerHTML = '<div class="alert alert-info">Execution is still running. Results will be available when execution completes.</div>';
        return;
    }

    const results = executionEndEvent.results || {};

    if (Object.keys(results).length === 0) {
        resultsContainer.innerHTML = '<div class="alert alert-info">No results available.</div>';
        return;
    }

    let html = '<div class="accordion" id="resultsAccordion">';

    Object.keys(results).forEach((key, index) => {
        const value = results[key];
        const valueStr = typeof value === 'object' ? JSON.stringify(value, null, 2) : value.toString();

        html += `
            <div class="accordion-item">
                <h2 class="accordion-header" id="heading${index}">
                    <button class="accordion-button ${index === 0 ? '' : 'collapsed'}" type="button" data-bs-toggle="collapse" data-bs-target="#collapse${index}" aria-expanded="${index === 0 ? 'true' : 'false'}" aria-controls="collapse${index}">
                        ${escapeHtml(key)}
                    </button>
                </h2>
                <div id="collapse${index}" class="accordion-collapse collapse ${index === 0 ? 'show' : ''}" aria-labelledby="heading${index}" data-bs-parent="#resultsAccordion">
                    <div class="accordion-body">
                        <pre class="mb-0"><code>${escapeHtml(valueStr)}</code></pre>
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';
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

    document.getElementById('steps-container').innerHTML = '<div class="alert alert-danger">Error: ' + escapeHtml(message) + '</div>';
    document.getElementById('results-container').innerHTML = '<div class="alert alert-danger">Error: ' + escapeHtml(message) + '</div>';
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
