// Central export for all node type definitions
// Each node category/type lives in its own file for clarity & future growth

import { NodeTypeMap } from './NodeType.ts';
import { logNode } from './log.ts';
import { httpNode } from './http.ts';
import { sqlNode } from './sql.ts';
import { scriptNode } from './script.ts';
import { secretNode } from './secret.ts';
import { exportNode } from './export.ts';
import { pythonNode } from './python.ts';
import { workbookNode } from './workbook.ts';
import { defaultNode } from './default.ts';

export const nodeTypeMap: NodeTypeMap = {
    [logNode.type]: logNode,
    [httpNode.type]: httpNode,
    [sqlNode.type]: sqlNode,
    [scriptNode.type]: scriptNode,
    [secretNode.type]: secretNode,
    [exportNode.type]: exportNode,
    [pythonNode.type]: pythonNode,
    [workbookNode.type]: workbookNode,
    [defaultNode.type]: defaultNode,
};

export const orderedNodeTypes = [
    'log',
    'http',
    'sql',
    'script',
    'secret',
    'export',
    'python',
    'workbook',
    'default'
];

export * from './NodeType.ts';
