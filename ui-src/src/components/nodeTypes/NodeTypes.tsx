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
import StartNode from '../nodes/start/start';
import EndNode from '../nodes/end/end';
import HttpNode from '../nodes/http/http';
import PythonNode from '../nodes/python/python';
import DuckDbNode from '../nodes/duckdb/duckdb';
import PostgresNode from '../nodes/postgres/postgres';
import PlaybooksNode from '../nodes/playbooks/playbooks';
import LoopNode from '../nodes/loop/loop';
import WorkbookNode from '../nodes/workbook/workbook';

// Direct mapping (no adapter) using new NodeProps-style components
export const nodeTypes = {
    start: StartNode,
    end: EndNode,
    http: HttpNode,
    python: PythonNode,
    duckdb: DuckDbNode,
    postgres: PostgresNode,
    playbooks: PlaybooksNode,
    loop: LoopNode,
    workbook: WorkbookNode,
};

export const initNodes = [
    { id: 'start', type: 'start', data: { name: 'start' }, position: { x: 0, y: 0 } },
    { id: 'http1', type: 'http', data: { name: 'http', url: 'https://example.com', method: 'GET' }, position: { x: 200, y: 0 } },
    { id: 'end', type: 'end', data: { name: 'end' }, position: { x: 400, y: 0 } },
];

export const initEdges: Edge[] = [
    { id: 'e-start-http', source: 'start', target: 'http1' },
    { id: 'e-http-end', source: 'http1', target: 'end' },
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
