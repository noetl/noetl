import React from 'react';
import { Input, Switch } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const PythonEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor python-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">Module or Script</span>
                <Input
                    className="xy-theme__input nodrag"
                    value={config.module || ''}
                    onChange={(e) => setConfig('module', e.target.value)}
                    placeholder="module.path:function or leave empty for inline"
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">Inline Code</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={6}
                    value={config.code || ''}
                    onChange={(e) => setConfig('code', e.target.value)}
                    placeholder="# Write Python code here"
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">Use Virtualenv</span>
                <Switch
                    className="nodrag"
                    checked={!!config.useVenv}
                    onChange={(checked) => setConfig('useVenv', checked)}
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const pythonNode: NodeTypeDef = {
    type: 'python',
    label: 'Python',
    icon: '🐍',
    color: '#3776ab',
    description: 'Execute Python code.',
    editor: PythonEditor,
};
