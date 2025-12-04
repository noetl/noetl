import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './StartNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

interface StartNodeData {
    name?: string;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function StartNodeInternal({ id, data = {} }: NodeProps<Node<StartNodeData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ name: '' });

    const openEditor = () => {
        setDraft({
            name: data.name || 'start'
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            name: draft.name
        });
        setModalOpen(false);
    };

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="StartNode" onDoubleClick={openEditor}>
            <Handle type="source" position={Position.Right} />
            <div className="StartNode__header">
                <span className="StartNode__header-text">🚀 {data.name || 'start'}</span>
                <div className="StartNode__header-buttons">
                    <Tooltip title="Edit Start node">
                        <Button
                            className="start-edit-btn"
                            size="small"
                            type="text"
                            icon={<EditOutlined />}
                            onPointerDown={preventNodeDrag}
                            onMouseDown={preventNodeDrag}
                            onClick={(e) => { preventNodeDrag(e); openEditor(); }}
                        />
                    </Tooltip>
                    {!data.readOnly && data.onDelete && (
                        <Tooltip title="Delete node">
                            <Button
                                className="start-delete-btn"
                                size="small"
                                type="text"
                                danger
                                icon={<DeleteOutlined />}
                                onPointerDown={preventNodeDrag}
                                onMouseDown={preventNodeDrag}
                                onClick={(e) => { preventNodeDrag(e); data.onDelete?.(id); }}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
            <div className="StartNode__label">Start</div>
            <div className="StartNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title="Start Node Config"
                width={480}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="StartNodeModal__container">
                    <div className="StartNodeModal__section-title">Name</div>
                    <Input
                        className="StartNodeModal__name"
                        value={draft.name}
                        placeholder='start'
                        onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                    />
                </div>
            </Modal>
        </div>
    );
}

export const StartNode = memo(StartNodeInternal);
