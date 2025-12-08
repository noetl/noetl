import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './HttpNode.less';
import { Modal, Input, Select, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { CodeEditor } from '../../CodeEditor';
import { NodeDocumentation } from '../NodeDocumentation';

interface HttpData {
    name?: string;
    method?: string;
    endpoint?: string;
    headers?: Record<string, any>;
    params?: Record<string, any>;
    payload?: Record<string, any>;
    data?: Record<string, any>;
    auth?: any;
    timeout?: number;
    verify_ssl?: boolean;
    task?: { name?: string; description?: string };
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function HttpNodeInternal({ id, data = {} }: NodeProps<Node<HttpData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [docsOpen, setDocsOpen] = useState(false);
    const [draft, setDraft] = useState({
        method: 'GET',
        endpoint: '',
        headers: {} as Record<string, any>,
        params: {} as Record<string, any>,
        payload: {} as Record<string, any>,
        auth: undefined as any,
        timeout: 30,
        verify_ssl: true
    });
    const [headerInput, setHeaderInput] = useState('');
    const [paramsInput, setParamsInput] = useState('');
    const [payloadInput, setPayloadInput] = useState('');
    const [authInput, setAuthInput] = useState('');
    const [headerError, setHeaderError] = useState<string | null>(null);
    const [paramsError, setParamsError] = useState<string | null>(null);
    const [payloadError, setPayloadError] = useState<string | null>(null);
    const [authError, setAuthError] = useState<string | null>(null);

    const serializeObject = (obj?: Record<string, any>) => {
        try {
            return obj && Object.keys(obj).length ? JSON.stringify(obj, null, 2) : '';
        } catch { return ''; }
    };

    const openEditor = () => {
        setDraft({
            method: (data.method || 'GET').toUpperCase(),
            endpoint: data.endpoint || '',
            headers: data.headers || {},
            params: data.params || {},
            payload: data.payload || data.data || {},
            auth: data.auth,
            timeout: data.timeout ?? 30,
            verify_ssl: data.verify_ssl ?? true
        });
        setHeaderInput(serializeObject(data.headers));
        setParamsInput(serializeObject(data.params));
        setPayloadInput(serializeObject(data.payload || data.data));
        setAuthInput(serializeObject(data.auth));
        setHeaderError(null);
        setParamsError(null);
        setPayloadError(null);
        setAuthError(null);
        setModalOpen(true);
    };

    const commit = () => {
        let headersObj = draft.headers;
        let paramsObj = draft.params;
        let payloadObj = draft.payload;
        let authObj = draft.auth;

        if (headerInput && !headerError) {
            try { headersObj = JSON.parse(headerInput); } catch { }
        }
        if (paramsInput && !paramsError) {
            try { paramsObj = JSON.parse(paramsInput); } catch { }
        }
        if (payloadInput && !payloadError) {
            try { payloadObj = JSON.parse(payloadInput); } catch { }
        }
        if (authInput && !authError) {
            try { authObj = JSON.parse(authInput); } catch { }
        }

        updateNodeData(id, {
            method: draft.method || 'GET',
            endpoint: draft.endpoint,
            headers: headersObj,
            params: paramsObj,
            payload: payloadObj,
            auth: authObj,
            timeout: draft.timeout,
            verify_ssl: draft.verify_ssl
        });
        setModalOpen(false);
    };

    const handleJSONChange = (val: string, field: 'headers' | 'params' | 'payload' | 'auth') => {
        const setInput = field === 'headers' ? setHeaderInput : field === 'params' ? setParamsInput : setPayloadInput;
        const setError = field === 'headers' ? setHeaderError : field === 'params' ? setParamsError : setPayloadError;

        setInput(val);
        if (!val.trim()) {
            setError(null);
            setDraft(d => ({ ...d, [field]: {} }));
            return;
        }
        try {
            const parsed = JSON.parse(val);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                setError(null);
                setDraft(d => ({ ...d, [field]: parsed }));
            } else {
                setError(`${field} must be a JSON object`);
            }
        } catch (e: any) {
            setError(e.message || 'Invalid JSON');
        }
    };

    const summaryEndpoint = (() => {
        const u = (data.endpoint || '').trim();
        return !u ? '' : u.length < 34 ? u : u.slice(0, 31) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="HttpNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="HttpNode__header">
                <span className="HttpNode__header-text">🌐 http</span>
                <div className="HttpNode__header-buttons">
                    <Tooltip title="Edit HTTP config">
                        <Button
                            className="http-edit-btn"
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
                                className="http-delete-btn"
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
            <div className="HttpNode__summary">
                {data.task?.name || summaryEndpoint || <span className="HttpNode__empty-endpoint">(no description)</span>}
            </div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `HTTP Config: ${data.name}` : 'HTTP Config'}
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
                    <Button key="save" type="primary" onClick={commit} disabled={!!(headerError || paramsError || payloadError || authError)}>Save</Button>
                ]}
            >
                <div className="HttpNodeModal__container">
                    <div className="HttpNodeModal__row">
                        <Select
                            className="HttpNodeModal__select"
                            value={draft.method}
                            onChange={(v) => setDraft(d => ({ ...d, method: v }))}
                            options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(m => ({ value: m, label: m }))}
                        />
                        <Input
                            value={draft.endpoint}
                            placeholder='{{ api }}/users/{{ user_id }}'
                            onChange={e => setDraft(d => ({ ...d, endpoint: e.target.value }))}
                        />
                    </div>
                    <div className="HttpNodeModal__row">
                        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                            <div style={{ flex: 1 }}>
                                <div className="HttpNodeModal__section-title">Timeout (seconds)</div>
                                <Input
                                    type="number"
                                    value={draft.timeout}
                                    placeholder="30"
                                    onChange={e => setDraft(d => ({ ...d, timeout: parseInt(e.target.value) || 30 }))}
                                />
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '20px' }}>
                                <input
                                    type="checkbox"
                                    checked={draft.verify_ssl}
                                    onChange={e => setDraft(d => ({ ...d, verify_ssl: e.target.checked }))}
                                    style={{ cursor: 'pointer' }}
                                />
                                <label style={{ cursor: 'pointer', margin: 0 }}>Verify SSL</label>
                            </div>
                        </div>
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Auth (JSON object)</div>
                        <CodeEditor
                            value={authInput}
                            onChange={val => handleJSONChange(val, 'auth')}
                            language="json"
                            height={100}
                            placeholder='{"type": "oauth2_client_credentials", "provider": "secret_manager"}'
                        />
                        {authError && <div className="HttpNodeModal__error">{authError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Headers (JSON object)</div>
                        <CodeEditor
                            value={headerInput}
                            onChange={val => handleJSONChange(val, 'headers')}
                            language="json"
                            height={120}
                            placeholder='{"Authorization": "Bearer {{ token }}"}'
                        />
                        {headerError && <div className="HttpNodeModal__error">{headerError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Params (JSON object)</div>
                        <CodeEditor
                            value={paramsInput}
                            onChange={val => handleJSONChange(val, 'params')}
                            language="json"
                            height={100}
                            placeholder='{"limit": 10}'
                        />
                        {paramsError && <div className="HttpNodeModal__error">{paramsError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Payload (JSON object)</div>
                        <CodeEditor
                            value={payloadInput}
                            onChange={val => handleJSONChange(val, 'payload')}
                            language="json"
                            height={120}
                            placeholder='{"query": "{{ search_term }}"}'
                        />
                        {payloadError && <div className="HttpNodeModal__error">{payloadError}</div>}
                    </div>
                </div>
            </Modal>

            <NodeDocumentation
                open={docsOpen}
                onClose={() => setDocsOpen(false)}
                nodeType="http"
            />
        </div>
    );
}

export const HttpNode = memo(HttpNodeInternal);
