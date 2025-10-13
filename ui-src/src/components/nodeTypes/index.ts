// Barrel re-export for node types (single public entrypoint)
export * from './NodeTypes';
export { default } from './NodeTypes'; import React, { ComponentType, ReactNode } from 'react';

// Individual node components
import StartNode from '../nodes/start/start';
import EndNode from '../nodes/end/end';
import WorkbookNode from '../nodes/workbook/workbook';
import PythonNode from '../nodes/python/python';
import HttpNode from '../nodes/http/http';
import DuckDbNode from '../nodes/duckdb/duckdb';
import PostgresNode from '../nodes/postgres/postgres';
// import SecretsNode from '../nodes/secrets/secrets'; // placeholder for future
import PlaybooksNode from '../nodes/playbooks/playbooks';
import LoopNode from '../nodes/loop/loop';

// Map used by React Flow
export const nodeTypes = {
    start: StartNode,
    end: EndNode,
    workbook: WorkbookNode,
    python: PythonNode,
    http: HttpNode,
    duckdb: DuckDbNode,
    postgres: PostgresNode,
    // secrets: SecretsNode,
    playbooks: PlaybooksNode,
    loop: LoopNode,
};

// Import per-node meta exports so metadata lives with each widget
import { startMeta } from '../nodes/start/start';
import { endMeta } from '../nodes/end/end';
import { workbookMeta } from '../nodes/workbook/workbook';
import { pythonMeta } from '../nodes/python/python';
import { httpMeta } from '../nodes/http/http';
import { duckdbMeta } from '../nodes/duckdb/duckdb';
import { postgresMeta } from '../nodes/postgres/postgres';
import { playbooksMeta } from '../nodes/playbooks/playbooks';
import { loopMeta } from '../nodes/loop/loop';
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

// Lightweight local error boundary (no JSX usage in this file)
class LocalErrorBoundary extends React.Component<{ fallback: ReactNode; children?: ReactNode }, { hasError: boolean }> {
    constructor(props: any) { super(props); this.state = { hasError: false }; }
    static getDerivedStateFromError() { return { hasError: true }; }
    componentDidCatch(err: any) { console.error('Node render error', err); }
    render() { return this.state.hasError ? this.props.fallback as any : (this.props.children as any); }
}

// Dispatcher props
interface NodeRendererProps { type: string; data: any; }

// Create element helper to avoid JSX in .ts file
const h = React.createElement;

export function NodeRenderer({ type, data }: NodeRendererProps) {
    return h(
        LocalErrorBoundary,
        { fallback: h('div', { style: { fontSize: 11 } }, 'Unsupported node type') },
        h(NodeRendererInner, { type, data })
    );
}

export function NodeRendererInner({ type, data }: NodeRendererProps): React.ReactElement {
    switch (type) {
        case 'start': return h(StartNode as ComponentType<any>, { data });
        case 'end': return h(EndNode as ComponentType<any>, { data });
        case 'workbook': return h(WorkbookNode as ComponentType<any>, { data });
        case 'python': return h(PythonNode as ComponentType<any>, { data });
        case 'http': return h(HttpNode as ComponentType<any>, { data });
        case 'duckdb': return h(DuckDbNode as ComponentType<any>, { data });
        case 'postgres': return h(PostgresNode as ComponentType<any>, { data });
        case 'playbooks': return h(PlaybooksNode as ComponentType<any>, { data });
        case 'loop': return h(LoopNode as ComponentType<any>, { data });
        // case 'secrets': return h(SecretsNode as ComponentType<any>, { data });
        default: return h('div', { style: { fontSize: 11, padding: 4 } }, `Unknown node: ${type}`);
    }
}

const META_MAP: Record<string, any> = {
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

export function getNodeMeta(type: string) {
    return META_MAP[type] || { icon: '❓', label: type };
}
