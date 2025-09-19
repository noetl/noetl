import React from 'react';
import { Input, Select } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

const HttpEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor http-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">Endpoint</span>
                <Input
                    className="xy-theme__input nodrag"
                    value={config.url || ''}
                    onChange={(e) => setConfig('url', e.target.value)}
                    placeholder="https://api.example.com/resource"
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">Method</span>
                <Select
                    className="flow-node-select nodrag"
                    value={config.method || 'GET'}
                    onChange={(val) => setConfig('method', val)}
                    options={methods.map(m => ({ value: m, label: m }))}
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">Headers (JSON)</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={2}
                    value={config.headersJSON || ''}
                    onChange={(e) => setConfig('headersJSON', e.target.value)}
                    placeholder='{"Authorization": "Bearer ..."}'
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">Params/Payload (JSON)</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={3}
                    value={config.payloadJSON || ''}
                    onChange={(e) => setConfig('payloadJSON', e.target.value)}
                    placeholder='{"id": 123, "q": "text"}'
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const httpNode: NodeTypeDef = {
    type: 'http',
    label: 'HTTP',
    icon: '🌐',
    color: '#1890ff',
    description: 'Makes an HTTP call.',
    editor: HttpEditor,
};
