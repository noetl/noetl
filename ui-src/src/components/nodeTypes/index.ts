// Central export for all node type definitions
// Each node category/type now lives in its own folder under ../nodes/[type]/index.tsx

// Refactored to example style: import default React components, build nodeTypes map for ReactFlow
import StartNode from '../nodes/start/start';
import EndNode from '../nodes/end/end';
import WorkbookNode from '../nodes/workbook/workbook';
import PythonNode from '../nodes/python/python';
import HttpNode from '../nodes/http/http';
import DuckDbNode from '../nodes/duckdb/duckdb';
import PostgresNode from '../nodes/postgres/postgres';
// import SecretsNode from '../nodes/secrets/secrets';
import PlaybooksNode from '../nodes/playbooks/playbooks';
import LoopNode from '../nodes/loop/loop';

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
