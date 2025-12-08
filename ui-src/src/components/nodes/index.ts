import { StartNode } from './startnode/StartNode';
import { EndNode } from './endnode/EndNode';
import { HttpNode } from './httpnode/HttpNode';
import { PythonNode } from './pythonnode/PythonNode';
import { DuckDbNode } from './duckdbnode/DuckDbNode';
import { PostgresNode } from './postgresnode/PostgresNode';
import { PlaybooksNode } from './playbooksnode/PlaybooksNode';
import { LoopNode } from './loopnode';
import { WorkbookNode } from './workbooknode/WorkbookNode';

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