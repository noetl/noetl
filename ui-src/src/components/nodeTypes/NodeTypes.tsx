import { useCallback } from 'react';
import {
    ReactFlow,
    Controls,
    addEdge,
    useNodesState,
    useEdgesState,
    Background,
    type Edge,
    type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// Minimal node component imports (keep existing implementation files)
import { StartNode } from '../nodes/startnode/StartNode';
import { EndNode } from '../nodes/endnode/EndNode';
import { HttpNode } from '../nodes/httpnode/HttpNode';
import { PythonNode } from '../nodes/pythonnode/PythonNode';
import { DuckDbNode } from '../nodes/duckdbnode/DuckDbNode';
import { PostgresNode } from '../nodes/postgresnode/PostgresNode';
import { PlaybooksNode } from '../nodes/playbooksnode/PlaybooksNode';
import { WorkbookNode } from '../nodes/workbooknode/WorkbookNode';

// Direct mapping (no adapter) using new NodeProps-style components
export const nodeTypes = {
    start: StartNode,
    end: EndNode,
    http: HttpNode,
    python: PythonNode,
    duckdb: DuckDbNode,
    postgres: PostgresNode,
    playbooks: PlaybooksNode,
    workbook: WorkbookNode,
};

export const initNodes = [
    // Start node
    { id: 'start', type: 'start', data: { name: 'start' }, position: { x: 0, y: 200 } },

    // Data processing nodes (row 1)
    { id: 'http1', type: 'http', data: { name: 'http-api', method: 'GET', endpoint: '{{ api }}/users/{{ user_id }}', headers: { Authorization: 'Bearer {{ token }}' }, params: { limit: 10 }, payload: { query: '{{ search_term }}' } }, position: { x: 250, y: 50 } },
    { id: 'python1', type: 'python', data: { name: 'transform', code: 'def main(data):\n    return data' }, position: { x: 250, y: 150 } },
    { id: 'duckdb1', type: 'duckdb', data: { name: 'analytics', query: 'SELECT * FROM data' }, position: { x: 250, y: 250 } },

    // Database and orchestration nodes (row 2)
    { id: 'postgres1', type: 'postgres', data: { name: 'db-query', query: 'SELECT * FROM users' }, position: { x: 500, y: 50 } },
    { id: 'playbooks1', type: 'playbooks', data: { name: 'sub-playbook', path: 'catalog/example' }, position: { x: 500, y: 150 } },
    { id: 'workbook1', type: 'workbook', data: { name: 'example_task' }, position: { x: 500, y: 250 } },

    // End node
    { id: 'end', type: 'end', data: { name: 'end' }, position: { x: 750, y: 200 } },
];

export const initEdges: Edge[] = [
    // Start to processing nodes
    { id: 'e-start-http', source: 'start', target: 'http1' },
    { id: 'e-start-python', source: 'start', target: 'python1' },
    { id: 'e-start-duckdb', source: 'start', target: 'duckdb1' },

    // Processing to orchestration nodes
    { id: 'e-http-postgres', source: 'http1', target: 'postgres1' },
    { id: 'e-python-playbooks', source: 'python1', target: 'playbooks1' },
    { id: 'e-duckdb-workbook', source: 'duckdb1', target: 'workbook1' },

    // Orchestration to end
    { id: 'e-postgres-end', source: 'postgres1', target: 'end' },
    { id: 'e-playbooks-end', source: 'playbooks1', target: 'end' },
    { id: 'e-loop-end', source: 'loop1', target: 'end' },
];

const FlowCanvas = () => {
    const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges);
    const onConnect: OnConnect = useCallback(
        (connection) => setEdges((eds) => addEdge(connection, eds)),
        [setEdges],
    );
    return (
        <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
        >
            <Controls />
            <Background />
        </ReactFlow>
    );
};

export default FlowCanvas;
