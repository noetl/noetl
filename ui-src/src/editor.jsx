/**
 * @fileoverview Manages the NoETL Playbook Editor page.
 *
 * This script encapsulates all editor logic within an `EditorApp` object
 * to avoid global namespace pollution and manage state cleanly. It ensures
 * robust, asynchronous initialization of dependent libraries (Monaco, ReactFlow)
 * and uses secure, modern APIs for all DOM interactions.
 */

// Import CSS for styling
import '../static/css/main.css';

// --- MODULE-LEVEL STATE & UTILITIES ---

/**
 * A shared namespace for editor instances and state.
 */
const EditorApp = {
    // --- State ---
    playbook: {
        apiVersion: "noetl.io/v1",
        kind: "Playbook",
        name: "new-playbook",
        path: "",
        workload: {},
        workflow: []
    },
    selectedNode: null,
    isUpdating: false, // Prevents sync loops between editors

    // --- Editor Instances ---
    monaco: null,
    workloadEditor: null,
    yamlEditor: null,
    reactFlow: {
        setNodes: () => console.warn("ReactFlow not initialized."),
        setEdges: () => console.warn("ReactFlow not initialized."),
    },

    // --- Initialization ---

    /**
     * Main entry point, called on DOMContentLoaded.
     */
    async init() {
        console.log("Initializing EditorApp...");
        this.initDOMListeners();
        this.setupAntTabs();

        try {
            // Sequentially and safely initialize dependencies
            await this.loadMonacoEditor();
            await this.loadReactFlow();
            this.loadPlaybookFromURL();
        } catch (error) {
            console.error("Initialization failed:", error);
            this.showInfoMessage(error.message, 'error');
        }
    },

    /**
     * Attaches all static event listeners.
     */
    initDOMListeners() {
        document.getElementById('save-playbook').addEventListener('click', () => this.savePlaybook());
        document.getElementById('execute-playbook').addEventListener('click', () => this.executePlaybook());
        document.getElementById('export-yaml').addEventListener('click', () => this.exportYaml());
        document.getElementById('import-yaml').addEventListener('click', () => this.showImportModal());
        document.getElementById('confirm-import').addEventListener('click', () => this.importYaml());
        document.getElementById('add-step').addEventListener('click', () => this.addNode('step'));
        document.getElementById('add-task').addEventListener('click', () => this.addNode('task'));
        document.querySelector('#info-panel .ant-alert-close-icon')?.addEventListener('click', () => this.hideInfoMessage());

        // Properties panel event delegation
        const propertiesPanel = document.getElementById('properties-panel');
        propertiesPanel.addEventListener('click', (e) => {
            if (e.target.matches('button[data-action="update-node"]')) {
                this.updateNodeProperties();
            }
        });
    },

    /**
     * Loads the Monaco Editor library asynchronously.
     * @returns {Promise<void>}
     */
    loadMonacoEditor() {
        return new Promise((resolve, reject) => {
            if (window.monaco) {
                this.monaco = window.monaco;
                this.initMonacoInstances();
                return resolve();
            }
            require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.36.1/min/vs' }});
            require(['vs/editor/editor.main'], () => {
                console.log('Monaco editor loaded via require');
                this.monaco = window.monaco;
                this.initMonacoInstances();
                resolve();
            }, (error) => {
                reject(new Error("Failed to load Monaco Editor."));
            });
        });
    },

    /**
     * Creates instances of the Monaco editors once the library is loaded.
     */
    initMonacoInstances() {
        this.workloadEditor = this.monaco.editor.create(document.getElementById('workload-editor'), {
            value: JSON.stringify(this.playbook.workload, null, 2),
            language: 'json',
            theme: 'vs',
            automaticLayout: true
        });

        this.yamlEditor = this.monaco.editor.create(document.getElementById('yaml-editor'), {
            value: jsyaml.dump(this.playbook),
            language: 'yaml',
            theme: 'vs',
            automaticLayout: true
        });

        // Add listeners for two-way data binding
        this.workloadEditor.onDidChangeModelContent(() => this.syncFromWorkload());
        this.yamlEditor.onDidChangeModelContent(() => this.syncFromYaml());
    },

    /**
     * Loads ReactFlow, waiting for it to be available on the window.
     * @returns {Promise<void>}
     */
    loadReactFlow() {
        return new Promise((resolve, reject) => {
            const checkForLibs = () => {
                if (window.React && window.ReactDOM && window.ReactFlow) {
                    console.log("ReactFlow and dependencies are ready.");
                    this.initReactFlowInstance();
                    resolve();
                } else {
                    // If still not loaded after a reasonable time, reject.
                    if (Date.now() - startTime > 10000) { // 10-second timeout
                        reject(new Error("Failed to load ReactFlow library within 10 seconds."));
                    } else {
                        setTimeout(checkForLibs, 100); // Check again shortly
                    }
                }
            };
            const startTime = Date.now();
            checkForLibs();
        });
    },

    /**
     * Renders the ReactFlow component into the DOM.
     */
    initReactFlowInstance() {
        const container = document.getElementById('workflow-editor');
        const root = document.createElement('div');
        root.style.width = '100%';
        root.style.height = '100%';
        container.appendChild(root);

        const { ReactFlowProvider, Background, Controls, MiniMap, applyNodeChanges, applyEdgeChanges, addEdge } = window.ReactFlow;

        class FlowEditor extends React.Component {
            constructor(props) {
                super(props);
                this.state = { nodes: [], edges: [] };
                // Expose state setters to the parent EditorApp object
                EditorApp.reactFlow.setNodes = (updater) => this.setState(s => ({ nodes: typeof updater === 'function' ? updater(s.nodes) : updater }));
                EditorApp.reactFlow.setEdges = (updater) => this.setState(s => ({ edges: typeof updater === 'function' ? updater(s.edges) : updater }));
            }

            render() {
                return React.createElement(ReactFlowProvider, null,
                    React.createElement(window.ReactFlow, {
                        nodes: this.state.nodes,
                        edges: this.state.edges,
                        onNodesChange: (changes) => this.setState(s => ({ nodes: applyNodeChanges(changes, s.nodes) })),
                        onEdgesChange: (changes) => this.setState(s => ({ edges: applyEdgeChanges(changes, s.edges) })),
                        onConnect: (params) => this.setState(s => ({ edges: addEdge(params, s.edges) })),
                        onNodeClick: (event, node) => {
                            EditorApp.selectedNode = node;
                            EditorApp.renderNodeProperties(node);
                        },
                        fitView: true,
                        snapToGrid: true,
                    },
                    React.createElement(Background),
                    React.createElement(Controls),
                    React.createElement(MiniMap)
                ));
            }
        }
        ReactDOM.render(React.createElement(FlowEditor), root);
    },

    // --- DATA SYNC & UPDATES ---

    syncFromWorkload() {
        if (this.isUpdating) return;
        this.isUpdating = true;
        try {
            this.playbook.workload = JSON.parse(this.workloadEditor.getValue());
            this.updateYamlEditor();
        } catch (e) {
            // Error state is handled by Monaco's UI, no need for an alert here.
        }
        this.isUpdating = false;
    },

    syncFromYaml() {
        if (this.isUpdating) return;
        this.isUpdating = true;
        try {
            const newPlaybook = jsyaml.load(this.yamlEditor.getValue());
            if (newPlaybook && typeof newPlaybook === 'object') {
                this.playbook = newPlaybook;
                this.updateWorkloadEditor();
                this.updateWorkflowEditor();
            }
        } catch (e) {
            // Error state is handled by Monaco's UI.
        }
        this.isUpdating = false;
    },

    updateYamlEditor() {
        if (!this.yamlEditor || this.isUpdating) return;
        this.isUpdating = true;
        this.yamlEditor.setValue(jsyaml.dump(this.playbook));
        this.isUpdating = false;
    },

    updateWorkloadEditor() {
        if (!this.workloadEditor || this.isUpdating) return;
        this.isUpdating = true;
        this.workloadEditor.setValue(JSON.stringify(this.playbook.workload || {}, null, 2));
        this.isUpdating = false;
    },

    updateWorkflowEditor() {
        const { nodes, edges } = this.convertPlaybookToNodesAndEdges(this.playbook);
        this.reactFlow.setNodes(nodes);
        this.reactFlow.setEdges(edges);
    },

    // --- UI RENDERING & INTERACTIONS ---

    renderNodeProperties(node) {
        const panel = document.getElementById('properties-panel');
        panel.innerHTML = ''; // Clear previous content

        if (!node) {
            panel.innerHTML = `<div class="placeholder"><i class="fas fa-mouse-pointer"></i><p>Select a node to view its properties.</p></div>`;
            return;
        }

        const createField = (label, id, value, type = 'text') => {
            const formItem = document.createElement('div');
            formItem.className = 'ant-form-item';
            const labelEl = document.createElement('label');
            labelEl.className = 'ant-form-item-label';
            labelEl.htmlFor = id;
            labelEl.textContent = label;
            const inputEl = document.createElement(type === 'textarea' ? 'textarea' : 'input');
            inputEl.className = 'ant-input';
            inputEl.id = id;
            inputEl.value = value;
            if (type === 'textarea') inputEl.rows = 3;
            formItem.append(labelEl, inputEl);
            return formItem;
        };

        const title = document.createElement('h4');
        title.textContent = `${node.data.type.charAt(0).toUpperCase() + node.data.type.slice(1)} Properties`;
        panel.appendChild(title);

        if (node.data.type === 'step') {
            panel.appendChild(createField('Step Name:', 'prop-step-name', node.data.label));
            panel.appendChild(createField('Description:', 'prop-step-desc', node.data.desc, 'textarea'));
        }
        // Add more property fields for 'task', 'condition', etc.

        const updateButton = document.createElement('button');
        updateButton.className = 'ant-btn ant-btn-primary';
        updateButton.textContent = 'Update';
        updateButton.dataset.action = 'update-node';
        panel.appendChild(updateButton);
    },

    updateNodeProperties() {
        if (!this.selectedNode) return;
        const { id, data } = this.selectedNode;

        if (data.type === 'step') {
            const newName = document.getElementById('prop-step-name').value;
            const newDesc = document.getElementById('prop-step-desc').value;

            // Update ReactFlow node
            this.reactFlow.setNodes(nodes => nodes.map(n => {
                if (n.id === id) {
                    n.data = { ...n.data, label: newName, desc: newDesc };
                }
                return n;
            }));

            // Update playbook object
            const step = this.playbook.workflow.find(s => s.step === id);
            if (step) {
                step.step = newName;
                step.desc = newDesc;
            }
            // Also need to update edges if the ID (name) changed
            if (id !== newName) {
                this.reactFlow.setEdges(edges => edges.map(e => {
                    if (e.source === id) e.source = newName;
                    if (e.target === id) e.target = newName;
                    return e;
                }));
                this.selectedNode.id = newName; // Update the selected node's ID
            }
        }
        this.updateYamlEditor();
    },

    // --- PLAYBOOK ACTIONS (Save, Load, Execute, etc.) ---

    async savePlaybook() {
        try {
            const yaml = this.yamlEditor.getValue();
            const content_base64 = btoa(unescape(encodeURIComponent(yaml))); // UTF-8 safe btoa
            const response = await fetch('/catalog/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content_base64 }),
            });
            if (!response.ok) throw new Error('Server responded with an error.');
            const data = await response.json();
            this.showInfoMessage(`Playbook saved. Path: ${data.path}, Version: ${data.version}`, 'success');
            // Update URL to reflect saved playbook path
            if (window.location.pathname.includes('/new')) {
                window.history.replaceState({}, '', `/editor/${encodeURIComponent(data.path)}/${encodeURIComponent(data.version)}`);
            }
        } catch (error) {
            this.showInfoMessage(`Error saving playbook: ${error.message}`, 'error');
        }
    },

    loadPlaybookFromURL() {
        const pathParts = window.location.pathname.split('/');
        if (pathParts.length >= 3 && (pathParts[1] === 'editor' || pathParts[1] === 'playbook') && pathParts[2] !== 'new') {
            const path = decodeURIComponent(pathParts[2]);
            const version = pathParts.length >= 4 ? decodeURIComponent(pathParts[3]) : 'latest';
            this.loadPlaybook(path, version);
        }
    },

    async loadPlaybook(path, version) {
        try {
            const response = await fetch(`/catalog/${encodeURIComponent(path)}/${encodeURIComponent(version)}`);
            if (!response.ok) throw new Error('Playbook not found or server error.');
            const data = await response.json();
            if (!data.content) throw new Error('Playbook content is empty.');

            this.playbook = jsyaml.load(data.content);
            document.getElementById('editor-title').textContent = `Editing: ${this.playbook.name || path}`;
            this.updateAllEditors();
        } catch (error) {
            this.showInfoMessage(`Error loading playbook: ${error.message}`, 'error');
        }
    },

    updateAllEditors() {
        this.isUpdating = true;
        this.updateYamlEditor();
        this.updateWorkloadEditor();
        this.updateWorkflowEditor();
        this.isUpdating = false;
    },

    // --- UTILITY METHODS ---
    // (showInfoMessage, hideInfoMessage, convertPlaybookToNodesAndEdges, etc. would be here)
    // For brevity, these are omitted but would be part of the EditorApp object.
    showInfoMessage(message, type = 'info') {
        const infoPanel = document.getElementById('info-panel');
        const infoMessage = document.getElementById('info-message');
        if (!infoPanel || !infoMessage) return;
        infoMessage.textContent = message;
        infoPanel.className = `ant-alert ant-alert-${type} ant-alert-with-description ant-alert-closable`;
        infoPanel.style.display = 'flex';
    },

    hideInfoMessage() {
        const infoPanel = document.getElementById('info-panel');
        if (infoPanel) infoPanel.style.display = 'none';
    },

    convertPlaybookToNodesAndEdges(playbook) {
        const nodes = [];
        const edges = [];
        if (!playbook.workflow || !Array.isArray(playbook.workflow)) return { nodes, edges };

        playbook.workflow.forEach((step, index) => {
            nodes.push({
                id: step.step,
                type: 'default',
                position: { x: 250, y: index * 150 },
                data: { label: step.step, desc: step.desc || '', type: 'step', config: step },
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
                                label: next.when || 'next',
                            });
                        });
                    }
                });
            }
        });
        return { nodes, edges };
    },
    // Other methods like executePlaybook, exportYaml, etc. would also be moved into this object.
};

// --- SCRIPT ENTRY POINT ---
document.addEventListener('DOMContentLoaded', () => {
    EditorApp.init();
});
