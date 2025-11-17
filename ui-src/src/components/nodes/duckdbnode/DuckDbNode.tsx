import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './DuckDbNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

interface DuckDbData {
    name?: string;
    query?: string;
    file?: string;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function DuckDbNodeInternal({ id, data = {} }: NodeProps<Node<DuckDbData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({
        query: '',
        file: ''
    });

    const openEditor = () => {
        setDraft({
            query: data.query || '',
            file: data.file || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            query: draft.query,
            file: draft.file
        });
        setModalOpen(false);
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
        <div className="DuckDbNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="DuckDbNode__header">
                <span className="DuckDbNode__header-text">🦆 {data.name || 'duckdb'}</span>
                <div className="DuckDbNode__header-buttons">
                    <Tooltip title="Edit DuckDB query">
                        <Button
                            className="duckdb-edit-btn"
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
                                className="duckdb-delete-btn"
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
            <div className="DuckDbNode__summary">
                {summaryQuery || <span className="DuckDbNode__empty-query">(no query)</span>}
            </div>
            <div className="DuckDbNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `DuckDB Config: ${data.name}` : 'DuckDB Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="DuckDbNodeModal__container">
                    <div>
                        <div className="DuckDbNodeModal__section-title">Query</div>
                        <Input.TextArea
                            className="DuckDbNodeModal__query"
                            value={draft.query}
                            rows={8}
                            placeholder="SELECT * FROM read_csv('{{ file_path }}')"
                            onChange={e => setDraft(d => ({ ...d, query: e.target.value }))}
                            style={{ fontFamily: 'monospace' }}
                        />
                    </div>
                    <div>
                        <div className="DuckDbNodeModal__section-title">File (Optional DuckDB file path)</div>
                        <Input
                            value={draft.file}
                            placeholder='{{ workload.csv_path }}'
                            onChange={e => setDraft(d => ({ ...d, file: e.target.value }))}
                        />
                    </div>
                </div>
            </Modal>
        </div>
    );
}

export const DuckDbNode = memo(DuckDbNodeInternal);
