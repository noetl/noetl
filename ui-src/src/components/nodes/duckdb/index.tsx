import React from 'react';
import { Input } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const DuckDbEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor duckdb-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">SQL</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={6}
                    value={config.sql || ''}
                    onChange={(e) => setConfig('sql', e.target.value)}
                    placeholder="-- DuckDB SQL here"
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const duckdbNode: NodeTypeDef = {
    type: 'duckdb',
    label: 'DuckDB',
    icon: '🦆',
    color: '#8c61ff',
    description: 'Executes DuckDB SQL.',
    editor: DuckDbEditor,
};
