import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

interface WorkbookData {
    name?: string;
    task?: string;
    withJSON?: string;
    [key: string]: unknown;
}

function WorkbookNode({ id, data }: NodeProps<Node<WorkbookData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'workbook';
    const task = data?.task || '';
    const withJSON = data?.withJSON || '';
    const withPreview = withJSON ? (withJSON.length > 40 ? withJSON.slice(0, 37) + '…' : withJSON) : '';
    return (
        <div style={{ padding: 8, border: '1px solid #ff6b35', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📊 {name}</div>
            <input
                style={{ width: '100%', fontSize: 11, marginBottom: 4 }}
                value={task}
                placeholder="task name"
                onChange={(e) => updateNodeData(id, { task: e.target.value })}
                className="xy-theme__input"
            />
            <textarea
                style={{ width: '100%', fontSize: 10, fontFamily: 'monospace', marginBottom: 4 }}
                rows={3}
                value={withJSON}
                placeholder="with JSON"
                onChange={(e) => updateNodeData(id, { withJSON: e.target.value })}
                className="xy-theme__input"
            />
            {withPreview && <div style={{ fontSize: 10, opacity: 0.6 }}>{withPreview}</div>}
        </div>
    );
}

export default memo(WorkbookNode);
