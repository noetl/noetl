import React from 'react';
import { Input } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const WorkbookEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor workbook-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">Task</span>
                <Input
                    className="xy-theme__input nodrag"
                    value={config.task || ''}
                    onChange={(e) => setConfig('task', e.target.value)}
                    placeholder="workbook.task_name"
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">with: (JSON)</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={4}
                    value={config.withJSON || ''}
                    onChange={(e) => setConfig('withJSON', e.target.value)}
                    placeholder='{"arg1": "value"}'
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const workbookNode: NodeTypeDef = {
    type: 'workbook',
    label: 'Workbook',
    icon: '📊',
    color: '#ff6b35',
    description: 'Invoke a workbook task.',
    editor: WorkbookEditor,
};
