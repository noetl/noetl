// Central export for all node type definitions
// Each node category/type now lives in its own folder under ../nodes/[type]/index.tsx

import { NodeTypeMap } from './NodeType.ts';

// Import node definitions from the new folder-based structure
import { startNode } from '../nodes/start';
import { endNode } from '../nodes/end';
import { workbookNode } from '../nodes/workbook';
import { pythonNode } from '../nodes/python';
import { httpNode } from '../nodes/http';
import { duckdbNode } from '../nodes/duckdb';
import { postgresNode } from '../nodes/postgres';
import { secretsNode } from '../nodes/secrets';
import { playbooksNode } from '../nodes/playbooks';
import { loopNode } from '../nodes/loop';

export const nodeTypeMap: NodeTypeMap = {
    [startNode.type]: startNode,
    [endNode.type]: endNode,
    [workbookNode.type]: workbookNode,
    [pythonNode.type]: pythonNode,
    [httpNode.type]: httpNode,
    [duckdbNode.type]: duckdbNode,
    [postgresNode.type]: postgresNode,
    [secretsNode.type]: secretsNode,
    [playbooksNode.type]: playbooksNode,
    [loopNode.type]: loopNode,
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

export * from './NodeType.ts';
