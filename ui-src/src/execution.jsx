/**
 * @fileoverview Manages the real-time display of playbook execution status and results.
 *
 * This script encapsulates all logic within an `ExecutionApp` object to manage state
 * and avoid global namespace pollution. It uses modern async/await for data fetching
 * and creates all DOM elements programmatically to ensure security and maintainability.
 */

// Import CSS for styling
import '../static/css/main.css';

// Import moment.js for date formatting
import moment from 'moment';

const ExecutionApp = {
    // --- State ---
    executionId: null,
    refreshIntervalId: null,
    REFRESH_INTERVAL_MS: 5000,

    // --- DOM Element Cache ---
    elements: {},

    // --- Initialization ---

    /**
     * Main entry point, called on DOMContentLoaded.
     */
    init() {
        console.log("Initializing ExecutionApp...");
        this.cacheDOMElements();
        this.initDOMListeners();

        const pathParts = window.location.pathname.split('/');
        if (pathParts.length >= 3 && pathParts[1] === 'execution') {
            this.executionId = decodeURIComponent(pathParts[2]);
            this.elements.title.textContent = `Execution: ${this.executionId}`;
            this.elements.id.textContent = this.executionId;
            this.loadExecutionData();
            this.refreshIntervalId = setInterval(() => this.loadExecutionData(), this.REFRESH_INTERVAL_MS);
        } else {
            this.showError('No execution ID provided in URL.');
        }
    },

    /**
     * Caches frequently accessed DOM elements for performance.
     */
    cacheDOMElements() {
        this.elements = {
            title: document.getElementById('execution-title'),
            id: document.getElementById('execution-id'),
            playbookPath: document.getElementById('playbook-path'),
            playbookVersion: document.getElementById('playbook-version'),
            startTime: document.getElementById('start-time'),
            endTime: document.getElementById('end-time'),
            duration: document.getElementById('duration'),
            statusContainer: document.getElementById('execution-status'),
            statusText: document.getElementById('status-text'),
            statusDetails: document.getElementById('status-details'),
            spinner: document.getElementById('execution-spinner'),
            stepsContainer: document.getElementById('steps-container'),
            resultsContainer: document.getElementById('results-container'),
        };
    },

    /**
     * Attaches all static event listeners.
     */
    initDOMListeners() {
        document.getElementById('refresh-execution').addEventListener('click', () => this.loadExecutionData());
        document.getElementById('back-to-catalog').addEventListener('click', () => {
            window.location.href = '/';
        });

        // Event delegation for dynamically created collapse panels
        this.elements.resultsContainer.addEventListener('click', (e) => {
            const header = e.target.closest('.ant-collapse-header');
            if (header) {
                this.toggleCollapsePanel(header);
            }
        });
    },

    // --- Data Fetching & Processing ---

    /**
     * Fetches and displays the execution data.
     */
    async loadExecutionData() {
        if (!this.executionId) return;

        try {
            let response = await fetch(`/execution/data/${encodeURIComponent(this.executionId)}`);
            // Fallback for backward compatibility
            if (!response.ok) {
                response = await fetch(`/events/query?event_id=${encodeURIComponent(this.executionId)}`);
            }
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const data = await response.json();
            this.render(data);
        } catch (error) {
            console.error('Error loading execution data:', error);
            this.showError('Error loading execution data. Please try again later.');
            clearInterval(this.refreshIntervalId);
        }
    },

    // --- DOM Rendering ---

    /**
     * Main render function to update the entire page from data.
     * @param {object} data The API response data.
     */
    render(data) {
        if (!data || !data.events || data.events.length === 0) {
            this.showError('No execution data found.');
            return;
        }
        const events = data.events;
        const startEvent = events.find(event => event.event_type === 'execution_start');
        if (!startEvent) {
            this.showError('Execution start event not found.');
            return;
        }

        const endEvent = events.find(event => event.event_type === 'execution_end' || event.event_type === 'execution_complete');

        this.renderHeader(startEvent, endEvent);
        this.renderStatus(endEvent, events);
        this.renderSteps(events);
        this.renderResults(endEvent);

        if (endEvent) {
            clearInterval(this.refreshIntervalId);
        }
    },

    /**
     * Renders the top-level execution summary header.
     */
    renderHeader(startEvent, endEvent) {
        this.elements.playbookPath.textContent = startEvent.resource_path || 'Unknown';
        this.elements.playbookVersion.textContent = startEvent.resource_version || 'Unknown';

        const startTime = new Date(startEvent.timestamp);
        this.elements.startTime.textContent = moment(startTime).format('YYYY-MM-DD HH:mm:ss');

        if (endEvent) {
            const endTime = new Date(endEvent.timestamp);
            this.elements.endTime.textContent = moment(endTime).format('YYYY-MM-DD HH:mm:ss');
            this.elements.duration.textContent = this.formatDuration(moment.duration(endTime - startTime));
        } else {
            this.elements.endTime.textContent = 'Still running...';
            this.elements.duration.textContent = this.formatDuration(moment.duration(moment() - startTime)) + ' (running)';
        }
    },

    /**
     * Updates the main status banner.
     */
    renderStatus(endEvent, events) {
        if (endEvent) {
            this.elements.spinner.style.display = 'none';
            if (endEvent.status === 'success') {
                this.elements.statusContainer.className = 'execution-status status-success';
                this.elements.statusText.textContent = 'Execution completed successfully';
                this.elements.statusDetails.textContent = endEvent.message || '';
            } else {
                this.elements.statusContainer.className = 'execution-status status-error';
                this.elements.statusText.textContent = 'Execution failed';
                this.elements.statusDetails.textContent = endEvent.error || endEvent.message || '';
            }
        } else {
            this.elements.statusContainer.className = 'execution-status status-running';
            this.elements.statusText.textContent = 'Execution in progress...';
            const latestEvent = events.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
            this.elements.statusDetails.textContent = latestEvent.message || '';
        }
    },

    /**
     * Renders the list of execution steps.
     */
    renderSteps(events) {
        this.elements.stepsContainer.innerHTML = ''; // Clear previous content
        const stepEvents = events.filter(e => e.event_type.startsWith('step_'));
        const transitionEvents = events.filter(e => e.event_type === 'step_transition');

        // Check if execution has completed
        const executionEndEvent = events.find(event => event.event_type === 'execution_end' || event.event_type === 'execution_complete');
        const isExecutionComplete = executionEndEvent && executionEndEvent.status === 'success';

        if (stepEvents.length === 0 && transitionEvents.length === 0) {
            this.elements.stepsContainer.appendChild(this.createAlert('No step events found.', 'info'));
            return;
        }

        // Group step events by name
        const stepsByName = stepEvents.reduce((acc, event) => {
            const stepName = event.node_name || event.step_name || 'unknown';
            if (!acc[stepName]) acc[stepName] = [];
            acc[stepName].push(event);
            return acc;
        }, {});

        // Add transition events to the steps map
        transitionEvents.forEach(event => {
            const metadata = event.metadata || {};
            const toStep = metadata.to_step;
            if (toStep && !stepsByName[toStep]) {
                stepsByName[toStep] = [];
            }
        });

        const listGroup = document.createElement('div');
        listGroup.className = 'ant-list';

        Object.entries(stepsByName).forEach(([stepName, stepEventsForName]) => {
            listGroup.appendChild(this.createStepElement(stepName, stepEventsForName, events, isExecutionComplete));
        });

        this.elements.stepsContainer.appendChild(listGroup);
    },

    /**
     * Creates a single DOM element for an execution step.
     * @returns {HTMLElement} The created list item element.
     */
    createStepElement(stepName, events, allEvents, isExecutionComplete) {
        // Check if this is a transition step
        const isTransition = stepName.startsWith('transition_to_');

        if (isTransition) {
            // Get the target step name (remove 'transition_to_' prefix)
            const targetStep = stepName.substring('transition_to_'.length);

            // Find if the target step has a completed event
            const targetStepEvents = allEvents.filter(e => 
                (e.node_name === targetStep || e.step_name === targetStep) && 
                (e.event_type === 'step_complete' || e.event_type === 'step_end')
            );

            // If the target step has completed events OR the execution is complete, mark this transition as complete
            const isTransitionComplete = targetStepEvents.length > 0 ||
                (isExecutionComplete && (targetStep === 'end' || stepName === 'transition_to_end'));

            if (isTransitionComplete) {
                const startEvent = events.find(e => e.event_type === 'step_transition');

                let statusClass = 'step-success';
                let statusIconClass = 'fas fa-arrow-right';
                let statusText = 'Complete';

                const item = document.createElement('div');
                item.className = `ant-list-item step-status ${statusClass}`;
                item.innerHTML = `
                    <div class="ant-list-item-meta">
                        <div class="ant-list-item-meta-content">
                            <h4 class="ant-list-item-meta-title">
                                <i class="${statusIconClass}" style="margin-right: 8px;"></i>
                                <strong>${this.escapeHtml(stepName)}</strong>
                            </h4>
                            <div class="ant-list-item-meta-description" style="margin-top: 12px; color: rgba(0, 0, 0, 0.65);">
                                <small style="display: block; margin-bottom: 4px;">
                                    <i class="fas fa-clock" style="margin-right: 8px;"></i>Started: ${startEvent ? moment(new Date(startEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss') : 'Unknown'}
                                </small>
                                <small style="display: block;"><i class="fas fa-flag-checkered" style="margin-right: 8px;"></i>Ended: Complete</small>
                            </div>
                        </div>
                    </div>
                    <span class="ant-tag">${statusText}</span>
                `;
                return item;
            }
        }

        const startEvent = events.find(e => e.event_type === 'step_start');
        const endEvent = events.find(e => e.event_type === 'step_end' || e.event_type === 'step_complete');

        let statusClass = 'step-running';
        let statusIconClass = 'fas fa-spinner fa-spin';
        let statusText = 'Running';

        if (endEvent) {
            statusClass = endEvent.status === 'success' ? 'step-success' : 'step-error';
            statusIconClass = endEvent.status === 'success' ? 'fas fa-check-circle' : 'fas fa-times-circle';
            statusText = endEvent.status === 'success' ? 'Success' : 'Failed';
        } else if (isExecutionComplete && stepName === 'end') {
            // Special case: if execution is complete and this is the 'end' step, mark it as successful
            statusClass = 'step-success';
            statusIconClass = 'fas fa-check-circle';
            statusText = 'Success';
        }

        const item = document.createElement('div');
        item.className = `ant-list-item step-status ${statusClass}`;

        // For the end step when execution is complete but no explicit end event exists
        const endTimeDisplay = endEvent ?
            moment(new Date(endEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss') :
            (isExecutionComplete && stepName === 'end' ? 'Complete' : '');

        item.innerHTML = `
            <div class="ant-list-item-meta">
                <div class="ant-list-item-meta-content">
                    <h4 class="ant-list-item-meta-title">
                        <i class="${statusIconClass}" style="margin-right: 8px;"></i>
                        <strong>${this.escapeHtml(stepName)}</strong>
                    </h4>
                    <div class="ant-list-item-meta-description" style="margin-top: 12px; color: rgba(0, 0, 0, 0.65);">
                        <small style="display: block; margin-bottom: 4px;">
                            <i class="fas fa-clock" style="margin-right: 8px;"></i>Started: ${startEvent ? moment(new Date(startEvent.timestamp)).format('YYYY-MM-DD HH:mm:ss') : 'Unknown'}
                        </small>
                        ${endTimeDisplay ? `<small style="display: block;"><i class="fas fa-flag-checkered" style="margin-right: 8px;"></i>Ended: ${endTimeDisplay}</small>` : ''}
                    </div>
                </div>
            </div>
            <span class="ant-tag">${statusText}</span>
        `;

        if (endEvent && endEvent.status !== 'success') {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-message';
            errorDiv.textContent = endEvent.error || 'Unknown error';
            item.querySelector('.ant-list-item-meta-description').appendChild(errorDiv);
        }

        return item;
    },

    /**
     * Renders the final execution results in an accordion.
     */
    renderResults(endEvent) {
        this.elements.resultsContainer.innerHTML = ''; // Clear previous
        if (!endEvent) {
            this.elements.resultsContainer.appendChild(this.createAlert('Execution is still running. Results will be available upon completion.', 'info'));
            return;
        }

        const results = endEvent.results || {};
        if (Object.keys(results).length === 0) {
            this.elements.resultsContainer.appendChild(this.createAlert('No results available for this execution.', 'info'));
            return;
        }

        const collapseContainer = document.createElement('div');
        collapseContainer.className = 'ant-collapse';

        Object.entries(results).forEach(([key, value], index) => {
            collapseContainer.appendChild(this.createResultPanel(key, value, index === 0));
        });

        this.elements.resultsContainer.appendChild(collapseContainer);
    },

    /**
     * Creates a single accordion panel for a result key.
     * @returns {HTMLElement} The created collapse item element.
     */
    createResultPanel(key, value, isActive) {
        const item = document.createElement('div');
        item.className = `ant-collapse-item ${isActive ? 'ant-collapse-item-active' : ''}`;
        item.innerHTML = `
            <div class="ant-collapse-header">
                <i class="ant-collapse-arrow" style="${isActive ? 'transform: rotate(90deg);' : ''}">
                    <svg viewBox="64 64 896 896" focusable="false" data-icon="right" width="12px" height="12px" fill="currentColor"><path d="M765.7 486.8L314.9 134.7A7.97 7.97 0 00302 141v77.3c0 4.9 2.3 9.6 6.1 12.6l360 281.1-360 281.1c-3.9 3-6.1 7.7-6.1 12.6V883c0 6.7 7.7 10.4 12.9 6.3l450.8-352.1a31.96 31.96 0 000-50.4z"></path></svg>
                </i>
                <span style="font-weight: 500;">${this.escapeHtml(key)}</span>
            </div>
            <div class="ant-collapse-content ${isActive ? 'ant-collapse-content-active' : 'ant-collapse-content-inactive'}" style="${isActive ? '' : 'display: none;'}">
                <div class="ant-collapse-content-box"></div>
            </div>
        `;

        const contentBox = item.querySelector('.ant-collapse-content-box');
        // Smart content rendering
        if (key.toLowerCase().includes('transition') || (typeof value === 'string' && value.includes('execution_id,from_step,to_step'))) {
            contentBox.appendChild(this.createTransitionTable(value));
        } else {
            const valueStr = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
            const pre = document.createElement('pre');
            pre.innerHTML = `<code>${this.escapeHtml(valueStr)}</code>`;
            contentBox.appendChild(pre);
        }
        return item;
    },

    /**
     * Creates an HTML table from CSV-like string data.
     * @returns {HTMLElement} The created table element.
     */
    createTransitionTable(csvString) {
        const table = document.createElement('table');
        table.className = 'ant-table';
        const lines = String(csvString).trim().split('\n');
        if (lines.length === 0) return table;

        const thead = table.createTHead();
        thead.className = 'ant-table-thead';
        const headerRow = thead.insertRow();
        lines[0].split(',').forEach(headerText => {
            const th = document.createElement('th');
            th.className = 'ant-table-cell';
            th.textContent = headerText;
            headerRow.appendChild(th);
        });

        const tbody = table.createTBody();
        tbody.className = 'ant-table-tbody';
        for (let i = 1; i < lines.length; i++) {
            const row = tbody.insertRow();
            row.className = 'ant-table-row';
            lines[i].split(',').forEach(cellText => {
                const cell = row.insertCell();
                cell.className = 'ant-table-cell';
                cell.textContent = cellText;
            });
        }
        const container = document.createElement('div');
        container.style.overflowX = 'auto';
        container.appendChild(table);
        return container;
    },

    // --- UI UTILITIES ---

    showError(message) {
        clearInterval(this.refreshIntervalId);
        this.elements.statusContainer.className = 'execution-status status-error';
        this.elements.statusText.textContent = 'Error';
        this.elements.statusDetails.textContent = message;
        this.elements.spinner.style.display = 'none';
        this.elements.stepsContainer.innerHTML = '';
        this.elements.stepsContainer.appendChild(this.createAlert(message, 'error'));
        this.elements.resultsContainer.innerHTML = '';
        this.elements.resultsContainer.appendChild(this.createAlert(message, 'error'));
    },

    createAlert(message, type = 'info') {
        const alertDiv = document.createElement('div');
        alertDiv.className = `ant-alert ant-alert-${type}`;
        alertDiv.innerHTML = `<span class="ant-alert-message">${this.escapeHtml(message)}</span>`;
        return alertDiv;
    },

    toggleCollapsePanel(header) {
        const item = header.closest('.ant-collapse-item');
        const content = item.querySelector('.ant-collapse-content');
        const arrow = header.querySelector('.ant-collapse-arrow');
        const isActive = item.classList.toggle('ant-collapse-item-active');

        content.classList.toggle('ant-collapse-content-active', isActive);
        content.classList.toggle('ant-collapse-content-inactive', !isActive);
        content.style.display = isActive ? 'block' : 'none';
        arrow.style.transform = isActive ? 'rotate(90deg)' : '';
    },

    formatDuration(duration) {
        const hours = Math.floor(duration.asHours());
        const minutes = duration.minutes();
        const seconds = duration.seconds();
        let result = '';
        if (hours > 0) result += `${hours}h `;
        if (minutes > 0 || hours > 0) result += `${minutes}m `;
        result += `${seconds}s`;
        return result;
    },

    escapeHtml(unsafe) {
        if (unsafe === null || unsafe === undefined) return '';
        const textNode = document.createTextNode(unsafe);
        const p = document.createElement('p');
        p.appendChild(textNode);
        return p.innerHTML;
    }
};

// --- SCRIPT ENTRY POINT ---
document.addEventListener('DOMContentLoaded', () => {
    ExecutionApp.init();
});
