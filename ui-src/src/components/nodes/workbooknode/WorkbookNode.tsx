import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import { Button, Modal, Input, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import './WorkbookNode.less';
import { NodeDocumentation } from '../NodeDocumentation';

interface WorkbookData {
    name?: string;
    task?: { name?: string; description?: string };
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function WorkbookNodeInternal({ id, data = {} }: NodeProps<Node<WorkbookData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [docsOpen, setDocsOpen] = useState(false);
    const [draft, setDraft] = useState({ name: '' });

    const openEditor = () => {
        setDraft({
            name: data.name || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            name: draft.name
        });
        setModalOpen(false);
    };

    const summaryName = (() => {
        const n = (data.name || '').trim();
        return !n ? '' : n.length < 30 ? n : n.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="WorkbookNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="WorkbookNode__header">
                <span className="WorkbookNode__header-text">📊 workbook</span>
                <div className="WorkbookNode__header-buttons">
                    <Tooltip title="Edit Workbook task">
                        <Button
                            className="workbook-edit-btn"
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
                                className="workbook-delete-btn"
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
            <div className="WorkbookNode__summary">
                {data.task?.name || summaryName || <span className="WorkbookNode__empty-task">(no description)</span>}
            </div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Workbook Config: ${data.name}` : 'Workbook Config'}
                width={640}
                footer={[
                    <Button
                        key="docs"
                        icon={<QuestionCircleOutlined />}
                        onClick={() => setDocsOpen(true)}
                        style={{ float: 'left' }}
                    >
                        Docs
                    </Button>,
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="WorkbookNodeModal__container">
                    <div className="WorkbookNodeModal__section-title">Task Name</div>
                    <Input
                        className="WorkbookNodeModal__name"
                        value={draft.name}
                        placeholder='example_task'
                        onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                    />
                </div>
            </Modal>

            <NodeDocumentation
                open={docsOpen}
                onClose={() => setDocsOpen(false)}
                nodeType="workbook"
            />
        </div>
    );
}

export const WorkbookNode = memo(WorkbookNodeInternal);
