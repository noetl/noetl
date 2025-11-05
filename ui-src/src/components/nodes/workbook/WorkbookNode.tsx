import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import { Button, Modal } from 'antd';
import './WorkbookNode.less';

interface WorkbookData { name?: string; task?: string; withJSON?: string;[key: string]: unknown; }

function WorkbookNode({ id, data }: NodeProps<Node<WorkbookData>>) {
    const { updateNodeData } = useReactFlow();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const name = data?.name || 'workbook';
    const task = data?.task || '';
    const withJSON = data?.withJSON || '';
    const withPreview = withJSON ? (withJSON.length > 40 ? withJSON.slice(0, 37) + '…' : withJSON) : '';
    return (
        <>
            <div className="WorkbookNode">
                <Handle type="target" position={Position.Left} />
                <Handle type="source" position={Position.Right} />
                <Button onClick={() => setIsModalOpen(true)} className="edit-node-btn">Edit</Button>
                <div className="WorkbookNode__title">📊 {name}</div>
                {withPreview && <div className="WorkbookNode__preview">{withPreview}</div>}
            </div>
            <Modal
                title={`test title`}
                open={isModalOpen}
                forceRender={false}
                destroyOnHidden={true}
                onOk={() => { console.log('Added folder:'); }}
                onCancel={() => setIsModalOpen(false)}
                okText="Edit"
                cancelText="Cancel"
            >
                <input
                    className="xy-theme__input WorkbookNode__input"
                    value={task}
                    placeholder="task name"
                    onChange={(e) => updateNodeData(id, { task: e.target.value })}
                />
                <textarea
                    className="xy-theme__input WorkbookNode__textarea"
                    rows={3}
                    value={withJSON}
                    placeholder="with JSON"
                    onChange={(e) => updateNodeData(id, { withJSON: e.target.value })}
                />
            </Modal>
        </>
    );
}

export default memo(WorkbookNode);
