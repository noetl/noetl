let workflowEditor;
let workloadEditor;
let yamlEditor;
let selectedNode = null;
let isUpdating = false;
let playbook = {
    apiVersion: "noetl.io/v1",
    kind: "Playbook",
    name: "",
    path: "",
    workload: {},
    workflow: []
};

document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        if (window.React && window.ReactDOM && window.ReactFlow) {
            console.log("Libraries loaded successfully, initializing editor");
            initReactFlow();
        } else {
            console.error("Required libraries not loaded:", {
                React: !!window.React,
                ReactDOM: !!window.ReactDOM,
                ReactFlow: !!window.ReactFlow
            });
            showInfoMessage('Error: Required libraries not loaded properly. Check console for details.', 'danger');
        }
    }, 2000); // Increased timeout to 2 seconds

    document.getElementById('save-playbook').addEventListener('click', savePlaybook);
    document.getElementById('execute-playbook').addEventListener('click', executePlaybook);
    document.getElementById('export-yaml').addEventListener('click', exportYaml);
    document.getElementById('import-yaml').addEventListener('click', showImportModal);
    document.getElementById('confirm-import').addEventListener('click', importYaml);

    document.getElementById('add-step').addEventListener('click', () => addNode('step'));
    document.getElementById('add-task').addEventListener('click', () => addNode('task'));
    document.getElementById('add-condition').addEventListener('click', () => addNode('condition'));
    document.querySelector('#info-panel .ant-alert-close-icon').addEventListener('click', function() {
        hideInfoMessage();
    });

    // Setup Ant Design tabs
    setupAntTabs();

    // Initialize Monaco editors and then load the playbook if needed
    initMonacoEditors();
});

function initMonacoEditors() {
    require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.36.1/min/vs' }});
    require(['vs/editor/editor.main'], function() {
        console.log('Monaco editor loaded');

        workloadEditor = monaco.editor.create(document.getElementById('workload-editor'), {
            value: JSON.stringify(playbook.workload, null, 2),
            language: 'json',
            theme: 'vs',
            automaticLayout: true
        });

        yamlEditor = monaco.editor.create(document.getElementById('yaml-editor'), {
            value: jsyaml.dump(playbook),
            language: 'yaml',
            theme: 'vs',
            automaticLayout: true
        });

        workloadEditor.onDidChangeModelContent(() => {
            if (isUpdating) return;
            try {
                isUpdating = true;
                playbook.workload = JSON.parse(workloadEditor.getValue());
                updateYamlEditor();
                isUpdating = false;
            } catch (e) {
                console.error('Invalid JSON in workload editor:', e);
                showInfoMessage('Error parsing JSON. The JSON might contain invalid syntax or be too complex.', 'danger');
                isUpdating = false;
            }
        });

        yamlEditor.onDidChangeModelContent(() => {
            if (isUpdating) return;
            try {
                isUpdating = true;
                const newPlaybook = jsyaml.load(yamlEditor.getValue());
                if (newPlaybook && typeof newPlaybook === 'object') {
                    playbook = newPlaybook;
                    updateWorkloadEditor();
                    updateWorkflowEditor();
                }
                isUpdating = false;
            } catch (e) {
                console.error('Invalid YAML in YAML editor:', e);
                showInfoMessage('Error parsing YAML. The YAML might contain invalid syntax, circular references, or be too complex.', 'danger');
                isUpdating = false;
            }
        });

        // Load playbook after editors are initialized
        const pathParts = window.location.pathname.split('/');
        if (pathParts.length >= 3 && (pathParts[1] === 'editor' || pathParts[1] === 'playbook') && pathParts[2] !== 'new') {
            // Load existing playbook
            const path = decodeURIComponent(pathParts[2]);
            const version = pathParts.length >= 4 ? decodeURIComponent(pathParts[3]) : 'latest';
            console.log('Loading playbook:', path, version);
            loadPlaybook(path, version);
        }
    });
}

function initReactFlow() {
    try {
        const container = document.getElementById('workflow-editor');
        if (!container) {
            console.error('Workflow editor container not found');
            showInfoMessage('Error initializing workflow editor. Container not found.', 'danger');
            return;
        }
        if (!window.React || !window.ReactDOM) {
            console.error('React or ReactDOM is not defined.');
            showInfoMessage('Error initializing workflow editor.', 'danger');
            return;
        }
        if (!window.ReactFlow) {
            console.error('ReactFlow is not defined.');
            showInfoMessage('Error initializing workflow editor.', 'danger');
            return;
        }

        console.log('Libraries loaded:', { 
            React: !!window.React, 
            ReactDOM: !!window.ReactDOM, 
            ReactFlow: !!window.ReactFlow 
        });
        const root = document.createElement('div');
        root.style.width = '100%';
        root.style.height = '100%';
        container.appendChild(root);
        const initialNodes = [];
        const initialEdges = [];

        class FlowEditor extends React.Component {
            constructor(props) {
                super(props);
                this.state = {
                    nodes: initialNodes,
                    edges: initialEdges
                };

                window.setNodes = (updater) => {
                    this.setState(prevState => ({
                        nodes: typeof updater === 'function' ? updater(prevState.nodes) : updater
                    }));
                };

                window.setEdges = (updater) => {
                    this.setState(prevState => ({
                        edges: typeof updater === 'function' ? updater(prevState.edges) : updater
                    }));
                };
            }

            render() {
                const { nodes, edges } = this.state;
                const { 
                    ReactFlowProvider, 
                    Background, 
                    Controls, 
                    MiniMap,
                    applyNodeChanges,
                    applyEdgeChanges,
                    addEdge
                } = window.ReactFlow;

                return React.createElement(
                    ReactFlowProvider,
                    null,
                    React.createElement(
                        window.ReactFlow,
                        {
                            nodes: nodes,
                            edges: edges,
                            onNodesChange: (changes) => {
                                this.setState(prevState => ({
                                    nodes: applyNodeChanges(changes, prevState.nodes)
                                }));
                            },
                            onEdgesChange: (changes) => {
                                this.setState(prevState => ({
                                    edges: applyEdgeChanges(changes, prevState.edges)
                                }));
                            },
                            onConnect: (params) => {
                                this.setState(prevState => ({
                                    edges: addEdge(params, prevState.edges)
                                }));
                            },
                            onNodeClick: (event, node) => {
                                selectedNode = node;
                                showNodeProperties(node);
                            },
                            fitView: true,
                            snapToGrid: true,
                            snapGrid: [15, 15],
                            defaultZoom: 1.5,
                            minZoom: 0.2,
                            maxZoom: 4,
                            attributionPosition: 'bottom-left'
                        },
                        [
                            React.createElement(Background, { color: '#aaa', gap: 16 }),
                            React.createElement(Controls),
                            React.createElement(MiniMap)
                        ]
                    )
                );
            }
        }

        ReactDOM.render(React.createElement(FlowEditor), root);

        workflowEditor = {
            container: container,
            root: root
        };

        console.log('React Flow initialized successfully');
    } catch (error) {
        console.error('Error initializing React Flow:', error);
        showInfoMessage('Error initializing workflow editor: ' + error.message, 'danger');
    }
}

function updateYamlEditor() {
    if (yamlEditor) {
        isUpdating = true;
        try {
            yamlEditor.setValue(jsyaml.dump(playbook));
        } catch (e) {
            console.error('Error converting playbook to YAML:', e);
            showInfoMessage('Error converting playbook to YAML. The playbook might contain circular references or be too complex.', 'danger');
        } finally {
            isUpdating = false;
        }
    }
}

function updateWorkloadEditor() {
    if (workloadEditor) {
        isUpdating = true;
        try {
            workloadEditor.setValue(JSON.stringify(playbook.workload || {}, null, 2));
        } catch (e) {
            console.error('Error converting workload to JSON:', e);
            showInfoMessage('Error converting workload to JSON. The workload might contain circular references or be too complex.', 'danger');
        } finally {
            isUpdating = false;
        }
    }
}

function updateWorkflowEditor() {
    if (window.setNodes && window.setEdges) {
        const { nodes, edges } = convertPlaybookToNodesAndEdges(playbook);
        window.setNodes(nodes);
        window.setEdges(edges);
    }
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


function convertPlaybookToNodesAndEdges(playbook) {
    const nodes = [];
    const edges = [];

    if (!playbook.workflow || !Array.isArray(playbook.workflow)) {
        return { nodes, edges };
    }

    playbook.workflow.forEach((step, index) => {
        nodes.push({
            id: step.step,
            type: 'default',
            position: { x: 250, y: index * 150 },
            data: { 
                label: step.step,
                desc: step.desc || '',
                type: 'step',
                config: step
            },
            className: 'node node-step'
        });

        if (step.next && Array.isArray(step.next)) {
            step.next.forEach((next, nextIndex) => {
                if (next.then && Array.isArray(next.then)) {
                    next.then.forEach((thenStep, thenIndex) => {
                        edges.push({
                            id: `${step.step}-${thenStep}-${nextIndex}-${thenIndex}`,
                            source: step.step,
                            target: thenStep,
                            label: next.when ? next.when : 'next',
                            labelStyle: { fill: '#333', fontWeight: 700 },
                            labelBgStyle: { fill: '#fff' },
                            style: { stroke: '#333' }
                        });
                    });
                }
            });
        }
    });

    return { nodes, edges };
}

function showNodeProperties(node) {
    const propertiesPanel = document.getElementById('properties-panel');

    if (!node) {
        propertiesPanel.innerHTML = `
            <div class="text-center text-muted">
                <p>Select a node to edit its properties</p>
            </div>
        `;
        return;
    }

    let html = '';

    if (node.data.type === 'step') {
        html = `
            <h4>Step Properties</h4>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="step-name" class="ant-form-item-label">Step Name:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <input type="text" class="ant-input" id="step-name" value="${escapeHtml(node.data.label)}">
                    </div>
                </div>
            </div>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="step-desc" class="ant-form-item-label">Description:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <textarea class="ant-input" id="step-desc" rows="3" style="resize: vertical;">${escapeHtml(node.data.desc)}</textarea>
                    </div>
                </div>
            </div>
            <button class="ant-btn ant-btn-primary" onclick="updateNodeProperties()">Update</button>
        `;
    } else if (node.data.type === 'task') {
        html = `
            <h4>Task Properties</h4>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="task-name" class="ant-form-item-label">Task Name:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <input type="text" class="ant-input" id="task-name" value="${escapeHtml(node.data.label)}">
                    </div>
                </div>
            </div>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="task-desc" class="ant-form-item-label">Description:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <textarea class="ant-input" id="task-desc" rows="3" style="resize: vertical;">${escapeHtml(node.data.desc)}</textarea>
                    </div>
                </div>
            </div>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="task-type" class="ant-form-item-label">Type:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <select class="ant-select" id="task-type" style="width: 100%;">
                            <option value="python" ${node.data.config.type === 'python' ? 'selected' : ''}>Python</option>
                            <option value="http" ${node.data.config.type === 'http' ? 'selected' : ''}>HTTP</option>
                            <option value="runner" ${node.data.config.type === 'runner' ? 'selected' : ''}>Runner</option>
                        </select>
                    </div>
                </div>
            </div>
            <button class="ant-btn ant-btn-primary" onclick="updateNodeProperties()">Update</button>
        `;
    } else if (node.data.type === 'condition') {
        html = `
            <h4>Condition Properties</h4>
            <div class="ant-form-item" style="margin-bottom: 16px;">
                <label for="condition-when" class="ant-form-item-label">When:</label>
                <div class="ant-form-item-control">
                    <div class="ant-form-item-control-input">
                        <input type="text" class="ant-input" id="condition-when" value="${escapeHtml(node.data.label)}">
                    </div>
                </div>
            </div>
            <button class="ant-btn ant-btn-primary" onclick="updateNodeProperties()">Update</button>
        `;
    }

    propertiesPanel.innerHTML = html;
}

function updateNodeProperties() {
    if (!selectedNode) return;

    if (selectedNode.data.type === 'step') {
        const name = document.getElementById('step-name').value;
        const desc = document.getElementById('step-desc').value;

        window.setNodes(nodes => 
            nodes.map(node => {
                if (node.id === selectedNode.id) {
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            label: name,
                            desc: desc,
                            config: {
                                ...node.data.config,
                                step: name,
                                desc: desc
                            }
                        }
                    };
                }
                return node;
            })
        );

        playbook.workflow = playbook.workflow.map(step => {
            if (step.step === selectedNode.id) {
                return {
                    ...step,
                    step: name,
                    desc: desc
                };
            }
            return step;
        });

        if (name !== selectedNode.id) {
            window.setEdges(edges => 
                edges.map(edge => {
                    if (edge.source === selectedNode.id) {
                        return {
                            ...edge,
                            source: name
                        };
                    }
                    if (edge.target === selectedNode.id) {
                        return {
                            ...edge,
                            target: name
                        };
                    }
                    return edge;
                })
            );

            selectedNode.id = name;
        }
    } else if (selectedNode.data.type === 'task') {
        const name = document.getElementById('task-name').value;
        const desc = document.getElementById('task-desc').value;
        const type = document.getElementById('task-type').value;

        window.setNodes(nodes => 
            nodes.map(node => {
                if (node.id === selectedNode.id) {
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            label: name,
                            desc: desc,
                            config: {
                                ...node.data.config,
                                task: name,
                                desc: desc,
                                type: type
                            }
                        }
                    };
                }
                return node;
            })
        );

        if (playbook.workbook) {
            playbook.workbook = playbook.workbook.map(task => {
                if (task.task === selectedNode.id) {
                    return {
                        ...task,
                        task: name,
                        desc: desc,
                        type: type
                    };
                }
                return task;
            });
        }
    } else if (selectedNode.data.type === 'condition') {
        const when = document.getElementById('condition-when').value;

        window.setNodes(nodes => 
            nodes.map(node => {
                if (node.id === selectedNode.id) {
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            label: when,
                            config: {
                                ...node.data.config,
                                when: when
                            }
                        }
                    };
                }
                return node;
            })
        );

        playbook.workflow.forEach(step => {
            if (step.next && Array.isArray(step.next)) {
                step.next.forEach(next => {
                    if (next.id === selectedNode.id) {
                        next.when = when;
                    }
                });
            }
        });
    }

    isUpdating = true;
    updateYamlEditor();
    isUpdating = false;
}

function addNode(type) {
    const id = `${type}_${Date.now()}`;
    let newNode;

    if (type === 'step') {
        newNode = {
            id: id,
            type: 'default',
            position: { x: 250, y: 100 },
            data: { 
                label: id,
                desc: 'New Step',
                type: 'step',
                config: {
                    step: id,
                    desc: 'New Step'
                }
            },
            className: 'node node-step'
        };

        if (!playbook.workflow) {
            playbook.workflow = [];
        }

        playbook.workflow.push({
            step: id,
            desc: 'New Step',
            next: []
        });
    } else if (type === 'task') {
        newNode = {
            id: id,
            type: 'default',
            position: { x: 250, y: 100 },
            data: { 
                label: id,
                desc: 'New Task',
                type: 'task',
                config: {
                    task: id,
                    desc: 'New Task',
                    type: 'python'
                }
            },
            className: 'node node-task'
        };

        if (!playbook.workbook) {
            playbook.workbook = [];
        }

        playbook.workbook.push({
            task: id,
            desc: 'New Task',
            type: 'python'
        });
    } else if (type === 'condition') {
        newNode = {
            id: id,
            type: 'default',
            position: { x: 250, y: 100 },
            data: { 
                label: 'condition',
                type: 'condition',
                config: {
                    when: 'condition'
                }
            },
            className: 'node node-condition'
        };

    }

    if (window.setNodes) {
        console.log('Adding node to workflow editor:', newNode);
        window.setNodes(nodes => [...nodes, newNode]);
    } else {
        console.error('window.setNodes is not defined.');
        showInfoMessage('Error adding node.', 'danger');
    }

    isUpdating = true;
    updateYamlEditor();
    isUpdating = false;
}


function savePlaybook() {
    const yaml = yamlEditor.getValue();
    const content_base64 = btoa(yaml);
    fetch('/catalog/register', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            content_base64: content_base64
        }),
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        showInfoMessage(`Playbook saved successfully. Path: ${data.path}, Version: ${data.version}`, 'success');
        if (window.location.pathname.includes('/editor/new')) {
            window.history.replaceState(
                {}, 
                document.title, 
                `/editor/${encodeURIComponent(data.path)}/${encodeURIComponent(data.version)}`
            );
        }
    })
    .catch(error => {
        console.error('Error saving playbook:', error);
        showInfoMessage('Error saving playbook. Please try again later.', 'danger');
    });
}

function executePlaybook() {
    const pathParts = window.location.pathname.split('/');
    if (pathParts.length < 3 || pathParts[1] !== 'editor' || pathParts[2] === 'new') {
        showInfoMessage('Please save the playbook before executing it.', 'warning');
        return;
    }

    const path = decodeURIComponent(pathParts[2]);
    const version = pathParts.length >= 4 ? decodeURIComponent(pathParts[3]) : 'latest';

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


function exportYaml() {
    const yaml = yamlEditor.getValue();
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${playbook.name || 'playbook'}.yaml`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}


function showImportModal() {
    const modal = document.getElementById('import-modal');
    modal.style.display = 'block';

    // Add event listener to close button
    const closeButton = modal.querySelector('.ant-modal-close');
    closeButton.addEventListener('click', function() {
        hideImportModal();
    });

    // Add event listener to cancel button
    const cancelButton = document.getElementById('modal-cancel');
    cancelButton.addEventListener('click', function() {
        hideImportModal();
    });
}


function hideImportModal() {
    const modal = document.getElementById('import-modal');
    modal.style.display = 'none';
}


function importYaml() {
    const yamlContent = document.getElementById('import-yaml-content').value;
    const fileInput = document.getElementById('import-yaml-file');

    if (yamlContent) {
        try {
            isUpdating = true;
            const importedPlaybook = jsyaml.load(yamlContent);
            if (importedPlaybook && typeof importedPlaybook === 'object') {
                playbook = importedPlaybook;
                updateYamlEditor();
                updateWorkloadEditor();
                updateWorkflowEditor();
                hideImportModal();
                isUpdating = false;
            } else {
                showInfoMessage('Invalid YAML content.', 'danger');
                isUpdating = false;
            }
        } catch (e) {
            console.error('Error parsing YAML:', e);
            showInfoMessage('Error parsing YAML. The YAML might contain invalid syntax, circular references, or be too complex. Please check the content and try again.', 'danger');
            isUpdating = false;
        }
    } else if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        const reader = new FileReader();

        reader.onload = function(e) {
            try {
                isUpdating = true;
                const importedPlaybook = jsyaml.load(e.target.result);
                if (importedPlaybook && typeof importedPlaybook === 'object') {
                    playbook = importedPlaybook;
                    updateYamlEditor();
                    updateWorkloadEditor();
                    updateWorkflowEditor();
                    hideImportModal();
                    isUpdating = false;
                } else {
                    showInfoMessage('Invalid YAML file.', 'danger');
                    isUpdating = false;
                }
            } catch (e) {
                console.error('Error parsing YAML file:', e);
                showInfoMessage('Error parsing YAML file. The YAML might contain invalid syntax, circular references, or be too complex. Please check the file and try again.', 'danger');
                isUpdating = false;
            }
        };

        reader.readAsText(file);
    } else {
        showInfoMessage('Please enter YAML content or select a file to import.', 'warning');
    }
}

function loadPlaybook(path, version) {
    fetch(`/catalog/${encodeURIComponent(path)}/${encodeURIComponent(version)}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            if (data.content) {
                try {
                    isUpdating = true;
                    playbook = jsyaml.load(data.content);
                    document.getElementById('editor-title').textContent = `Editing: ${playbook.name || path}`;
                    updateYamlEditor();
                    updateWorkloadEditor();
                    updateWorkflowEditor();
                    isUpdating = false;
                } catch (e) {
                    console.error('Error parsing playbook YAML:', e);
                    showInfoMessage('Error parsing playbook YAML. The playbook might contain invalid YAML syntax or be too complex.', 'danger');
                    isUpdating = false;
                }
            } else {
                showInfoMessage('Playbook content not found.', 'warning');
            }
        })
        .catch(error => {
            console.error('Error loading playbook:', error);
            showInfoMessage('Error loading playbook.', 'danger');
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

function setupAntTabs() {
    // Get all tab buttons
    const tabButtons = document.querySelectorAll('.ant-tabs-tab');

    // Add click event listeners to each tab button
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Get the tab ID from the data attribute
            const tabId = this.querySelector('.ant-tabs-tab-btn').getAttribute('data-tab-id');

            // Remove active class from all tab buttons
            tabButtons.forEach(btn => {
                btn.classList.remove('ant-tabs-tab-active');
            });

            // Add active class to the clicked tab button
            this.classList.add('ant-tabs-tab-active');

            // Hide all tab panes
            const tabPanes = document.querySelectorAll('.ant-tabs-tabpane');
            tabPanes.forEach(pane => {
                pane.style.display = 'none';
                pane.classList.remove('ant-tabs-tabpane-active');
            });

            // Show the selected tab pane
            const selectedPane = document.getElementById(tabId);
            if (selectedPane) {
                selectedPane.style.display = 'block';
                selectedPane.classList.add('ant-tabs-tabpane-active');
            }
        });
    });
}
