import React from 'react';

// Core type interfaces
export interface NodeMeta {
    type: string;
    icon: string;
    label: string;
    color: string;
    description?: string;
}

export interface NodeComponentProps {
    task: any;      // DSL task / step definition
    args: any;      // Alias for task.config (action configuration)
    readOnly?: boolean;
    onEdit?: (updatedTask: any) => void;
}

// Extended legacy node type definition (merged from former NodeType.ts)
export interface NodeEditorProps {
    task: any;
    readOnly?: boolean;
    updateField: (field: string, value: any) => void;
}

export interface NodeTypeDef {
    type: string;
    label: string;
    icon: string;
    color: string;
    description?: string;
    editor?: React.FC<NodeEditorProps>;
}

export type NodeTypeMap = Record<string, NodeTypeDef>;

// Local error boundary (lightweight)
class LocalErrorBoundary extends React.Component<{ fallback: React.ReactNode; children?: React.ReactNode }, { hasError: boolean }> {
    constructor(props: any) { super(props); this.state = { hasError: false }; }
    static getDerivedStateFromError() { return { hasError: true }; }
    componentDidCatch(err: any) { console.error('Node dispatcher error', err); }
    render() { return this.state.hasError ? (this.props.fallback as any) : (this.props.children as any); }
}

// Node components & their meta exports
import StartNode, { startMeta } from '../nodes/start/start';
import EndNode, { endMeta } from '../nodes/end/end';
import WorkbookNode, { workbookMeta } from '../nodes/workbook/workbook';
import PythonNode, { pythonMeta } from '../nodes/python/python';
import HttpNode, { httpMeta } from '../nodes/http/http';
import DuckDbNode, { duckdbMeta } from '../nodes/duckdb/duckdb';
import PostgresNode, { postgresMeta } from '../nodes/postgres/postgres';
import PlaybooksNode, { playbooksMeta } from '../nodes/playbooks/playbooks';
import LoopNode, { loopMeta } from '../nodes/loop/loop';

// Adapter to map ReactFlow node.data to standardized props
const adapt = (Comp: React.ComponentType<NodeComponentProps>) => (props: any) => {
    const task = props?.data?.task || {};
    return <Comp task={task} args={task.config} readOnly={props?.data?.readOnly} onEdit={props?.data?.onEdit} />;
};

// React Flow nodeTypes map
export const nodeTypes: Record<string, any> = {
    start: adapt(StartNode),
    end: adapt(EndNode),
    workbook: adapt(WorkbookNode),
    python: adapt(PythonNode),
    http: adapt(HttpNode),
    duckdb: adapt(DuckDbNode),
    postgres: adapt(PostgresNode),
    playbooks: adapt(PlaybooksNode),
    loop: adapt(LoopNode),
};

export const orderedNodeTypes = [
    'start',
    'workbook',
    'python',
    'http',
    'duckdb',
    'postgres',
    'secrets',
    'playbooks',
    'loop',
    'end',
];

// Dispatcher
interface NodeDispatcherProps { type: string | undefined; data: any; }

export function NodeDispatcher({ type, data }: NodeDispatcherProps) {
    return (
        <LocalErrorBoundary fallback={<div>Unsupported node type</div>}>
            <NodeDispatcherInner type={type} data={data} />
        </LocalErrorBoundary>
    );
}

export function NodeDispatcherInner({ type, data }: NodeDispatcherProps) {
    const task = (data as any)?.task || data?.task || data || {};
    const args = task?.config || {};
    switch (type) {
        case 'start': return <StartNode task={task} args={args} />;
        case 'end': return <EndNode task={task} args={args} />;
        case 'workbook': return <WorkbookNode task={task} args={args} />;
        case 'python': return <PythonNode task={task} args={args} />;
        case 'http': return <HttpNode task={task} args={args} />;
        case 'duckdb': return <DuckDbNode task={task} args={args} />;
        case 'postgres': return <PostgresNode task={task} args={args} />;
        case 'playbooks': return <PlaybooksNode task={task} args={args} />;
        case 'loop': return <LoopNode task={task} args={args} />;
        default: return <pre>Deprecated / Unknown node</pre>;
    }
}

// Aggregated meta lookup
const META_INDEX: Record<string, NodeMeta> = {
    start: startMeta,
    end: endMeta,
    workbook: workbookMeta,
    python: pythonMeta,
    http: httpMeta,
    duckdb: duckdbMeta,
    postgres: postgresMeta,
    playbooks: playbooksMeta,
    loop: loopMeta,
};

export function getNodeMeta(type?: string): Partial<NodeMeta> {
    return (type && META_INDEX[type]) || { icon: '❓', label: type || 'unknown', color: '#999' };
}

// Default aggregate export (optional convenience)
export default { nodeTypes, orderedNodeTypes, getNodeMeta };
