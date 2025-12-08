import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PlaybooksNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { NodeDocumentation } from '../NodeDocumentation';

interface PlaybooksData {
    name?: string;
    path?: string;
    entryStep?: string;
    returnStep?: string;
    entry_step?: string;
    return_step?: string;
    task?: { name?: string; description?: string };
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function PlaybooksNodeInternal({ id, data = {} }: NodeProps<Node<PlaybooksData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [docsOpen, setDocsOpen] = useState(false);
    const [draft, setDraft] = useState({
        path: '',
        entry_step: '',
        return_step: ''
    });

    const openEditor = () => {
        setDraft({
            path: data.path || '',
            entry_step: data.entry_step || '',
            return_step: data.return_step || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            path: draft.path,
            entry_step: draft.entry_step,
            return_step: draft.return_step
        });
        setModalOpen(false);
    };

    const summaryPath = (() => {
        const p = (data.path || '').trim();
        return !p ? '' : p.length < 30 ? p : p.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="PlaybooksNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PlaybooksNode__header">
                <span className="PlaybooksNode__header-text">📘 playbook</span>
                <div className="PlaybooksNode__header-buttons">
                    <Tooltip title="Edit Playbook path">
                        <Button
                            className="playbooks-edit-btn"
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
                                className="playbooks-delete-btn"
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
            <div className="PlaybooksNode__summary">
                {data.task?.name || summaryPath || <span className="PlaybooksNode__empty-path">(no description)</span>}
            </div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Playbook Config: ${data.name}` : 'Playbook Config'}
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
                <div className="PlaybooksNodeModal__container">
                    <div>
                        <div className="PlaybooksNodeModal__section-title">Catalog Path</div>
                        <Input
                            className="PlaybooksNodeModal__path"
                            value={draft.path}
                            placeholder='playbooks/user_scorer'
                            onChange={e => setDraft(d => ({ ...d, path: e.target.value }))}
                        />
                    </div>
                    <div>
                        <div className="PlaybooksNodeModal__section-title">Entry Step (Optional)</div>
                        <Input
                            value={draft.entry_step}
                            placeholder='start'
                            onChange={e => setDraft(d => ({ ...d, entry_step: e.target.value }))}
                        />
                    </div>
                    <div>
                        <div className="PlaybooksNodeModal__section-title">Return Step (Optional)</div>
                        <Input
                            value={draft.return_step}
                            placeholder='finalize'
                            onChange={e => setDraft(d => ({ ...d, return_step: e.target.value }))}
                        />
                    </div>
                </div>
            </Modal>

            <NodeDocumentation
                open={docsOpen}
                onClose={() => setDocsOpen(false)}
                nodeType="playbooks"
            />
        </div>
    );
}

export const PlaybooksNode = memo(PlaybooksNodeInternal);
