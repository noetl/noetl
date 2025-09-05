// NodeType.ts
// Defines the shape of a workflow node type and shared helpers

export interface NodeTypeDef {
    type: string;           // unique id used in playbook/task (e.g. 'log')
    label: string;          // human friendly label (e.g. 'Log')
    icon: string;           // small emoji/icon shown in the UI
    color: string;          // accent color
    description?: string;   // optional description for future tooltips
    // In the future we can add: configSchema, formComponent, validator, etc.
}

export type NodeTypeMap = Record<string, NodeTypeDef>;
