import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PostgresNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { CodeEditor } from '../../CodeEditor';

interface PostgresData {
    name?: string;
    query?: string;
    auth?: string;
    params?: Record<string, any>;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function PostgresNodeInternal({ id, data = {} }: NodeProps<Node<PostgresData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({
        query: '',
        auth: '',
        params: {} as Record<string, any>
    });
    const [paramsInput, setParamsInput] = useState('');
    const [paramsError, setParamsError] = useState<string | null>(null);

    const serializeObject = (obj?: Record<string, any>) => {
        try {
            return obj && Object.keys(obj).length ? JSON.stringify(obj, null, 2) : '';
        } catch { return ''; }
    };

    const openEditor = () => {
        setDraft({
            query: data.query || '',
            auth: data.auth || '',
            params: data.params || {}
        });
        setParamsInput(serializeObject(data.params));
        setParamsError(null);
        setModalOpen(true);
    };

    const commit = () => {
        let paramsObj = draft.params;
        if (paramsInput && !paramsError) {
            try { paramsObj = JSON.parse(paramsInput); } catch { }
        }

        updateNodeData(id, {
            query: draft.query,
            auth: draft.auth,
            params: paramsObj
        });
        setModalOpen(false);
    };

    const handleJSONChange = (val: string) => {
        setParamsInput(val);
        if (!val.trim()) {
            setParamsError(null);
            setDraft(d => ({ ...d, params: {} }));
            return;
        }
        try {
            const parsed = JSON.parse(val);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                setParamsError(null);
                setDraft(d => ({ ...d, params: parsed }));
            } else {
                setParamsError('params must be a JSON object');
            }
        } catch (e: any) {
            setParamsError(e.message || 'Invalid JSON');
        }
    };

    const summaryQuery = (() => {
        const q = (data.query || '').trim();
        return !q ? '' : q.length < 30 ? q : q.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="PostgresNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PostgresNode__header">
                <span className="PostgresNode__header-text">🐘 {data.name || 'postgres'}</span>
                <div className="PostgresNode__header-buttons">
                    <Tooltip title="Edit Postgres query">
                        <Button
                            className="postgres-edit-btn"
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
                                className="postgres-delete-btn"
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
            <div className="PostgresNode__summary">
                {summaryQuery || <span className="PostgresNode__empty-query">(no query)</span>}
            </div>
            <div className="PostgresNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Postgres Config: ${data.name}` : 'Postgres Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit} disabled={!!paramsError}>Save</Button>
                ]}
            >
                <div className="PostgresNodeModal__container">
                    <div>
                        <div className="PostgresNodeModal__section-title">Query</div>
                        <CodeEditor
                            value={draft.query}
                            onChange={value => setDraft(d => ({ ...d, query: value }))}
                            language="sql"
                            height={250}
                            placeholder='SELECT * FROM users WHERE id = %(user_id)s'
                        />
                    </div>
                    <div>
                        <div className="PostgresNodeModal__section-title">Auth (credential reference)</div>
                        <Input
                            value={draft.auth}
                            placeholder='pg_local'
                            onChange={e => setDraft(d => ({ ...d, auth: e.target.value }))}
                        />
                    </div>
                    <div>
                        <div className="PostgresNodeModal__section-title">Params (JSON object)</div>
                        <CodeEditor
                            value={paramsInput}
                            onChange={handleJSONChange}
                            language="json"
                            height={120}
                            placeholder='{"user_id": "{{ workload.user_id }}"}'
                        />
                        {paramsError && <div className="PostgresNodeModal__error">{paramsError}</div>}
                    </div>
                </div>
            </Modal>
        </div>
    );
}

export const PostgresNode = memo(PostgresNodeInternal);
