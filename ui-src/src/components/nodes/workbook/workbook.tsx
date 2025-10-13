import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeMeta, NodeComponentProps } from '../../nodeTypes';

// Minimal visual workbook node using standardized NodeComponentProps
function WorkbookNode({ task, args }: NodeComponentProps) {
    const cfg = args || {};
    return (
        <div style={{ padding: 8, border: '1px solid #ff6b35', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📊 {task.name || task.id || 'workbook'}</div>
            {cfg.task && <div><strong>task:</strong> {cfg.task}</div>}
            {cfg.withJSON && <div><strong>with:</strong> {(cfg.withJSON.length > 40) ? cfg.withJSON.slice(0, 37) + '…' : cfg.withJSON}</div>}
        </div>
    );
}

export default memo(WorkbookNode);

export const workbookMeta: NodeMeta = {
    type: 'workbook',
    icon: '📊',
    label: 'Workbook',
    color: '#ff6b35',
    description: 'Workbook execution step'
};
