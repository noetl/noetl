import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import { Button, Modal } from 'antd';

interface WorkbookData {
    name?: string;
    task?: string;
    withJSON?: string;
    [key: string]: unknown;
}

function WorkbookNode({ id, data }: NodeProps<Node<WorkbookData>>) {
    const { updateNodeData } = useReactFlow();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const name = data?.name || 'workbook';
    const task = data?.task || '';
    const withJSON = data?.withJSON || '';
    const withPreview = withJSON ? (withJSON.length > 40 ? withJSON.slice(0, 37) + '…' : withJSON) : '';
    return (<>
        <div style={{ padding: 8, border: '1px solid #ff6b35', borderRadius: 8, fontSize: 12, background: '#fff' }}
        >
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <Button onClick={() => setIsModalOpen(true)} className="edit-node-btn">Edit</Button>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📊 {name}</div>
            {withPreview && <div style={{ fontSize: 10, opacity: 0.6 }}>{withPreview}</div>}
        </div>
        <Modal
            title={`test title`}
            open={isModalOpen}
            forceRender={false}
            destroyOnHidden={true}
            onOk={() => {
                console.log('Added folder:');
            }}
            onCancel={() => setIsModalOpen(false)}
            okText="Edit"
            cancelText="Cancel"
        >
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
        </Modal>
    </>
    );
}

export default memo(WorkbookNode);
