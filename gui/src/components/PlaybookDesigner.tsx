import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  EdgeChange,
  Handle,
  MiniMap,
  Node,
  NodeChange,
  NodeProps,
  Position,
  ReactFlow,
  ReactFlowInstance,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Tabs,
  Typography,
  message,
} from "antd";
import {
  AimOutlined,
  ApartmentOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
} from "@ant-design/icons";
// @ts-ignore
import yaml from "js-yaml";
import "../styles/PlaybookDesigner.css";

const { Text, Title } = Typography;

type AnyRecord = Record<string, any>;

interface PlaybookDesignerProps {
  yamlContent: string;
  onYamlChange: (nextYaml: string) => void;
  playbookId?: string | null;
  onDrillDownPlaybook?: (path: string) => void;
}

interface StepDraftState {
  step: string;
  desc: string;
  specText: string;
  loopText: string;
  toolText: string;
  nextText: string;
  extraText: string;
}

interface RootDraftState {
  name: string;
  path: string;
  version: string;
  description: string;
  keychainText: string;
  executorText: string;
  workloadText: string;
  workbookText: string;
}

interface DesignerNodeData {
  step: string;
  kind: string;
  desc?: string;
  selected?: boolean;
  stepRef?: string;
  nodeRole?: "step" | "transition" | "place_in" | "place_out";
  initial?: boolean;
  terminal?: boolean;
  shape?: "process" | "subprocess" | "decision" | "terminator";
  playbookRef?: string;
  [key: string]: unknown;
}

type TaskAction = "continue" | "retry" | "jump" | "break" | "fail";

interface PipelinePolicyRuleDraft {
  id: string;
  mode: "when" | "else";
  when: string;
  do: TaskAction;
  attempts: string;
  backoff: string;
  delay: string;
  to: string;
  setIterText: string;
  setCtxText: string;
}

interface PipelineTaskDraft {
  id: string;
  name: string;
  kind: string;
  extraText: string;
  specText: string;
  rules: PipelinePolicyRuleDraft[];
}

interface ArcConditionBuilderDraft {
  left: string;
  operator: "==" | "!=" | ">" | ">=" | "<" | "<=" | "contains";
  valueType: "string" | "number" | "boolean" | "null";
  value: string;
}

const KNOWN_STEP_KEYS = new Set(["step", "desc", "spec", "loop", "tool", "next"]);

const DEFAULT_PLAYBOOK_DOC: AnyRecord = {
  apiVersion: "noetl.io/v2",
  kind: "Playbook",
  metadata: {
    name: "new_playbook",
    path: "examples/new_playbook",
    version: "1.0",
    description: "New playbook",
  },
  workload: {},
  workflow: [],
};

const COMMON_TOOL_KINDS = [
  "noop",
  "http",
  "postgres",
  "duckdb",
  "python",
  "workbook",
  "playbook",
  "script",
  "secrets",
];

const TRANSITION_NODE_PREFIX = "t:";
const PLACE_IN_NODE_PREFIX = "p_in:";
const PLACE_OUT_NODE_PREFIX = "p_out:";

type DesignerViewMode = "workflow" | "flowchart" | "petri";

function transitionNodeId(stepName: string): string {
  return `${TRANSITION_NODE_PREFIX}${stepName}`;
}

function placeInNodeId(stepName: string): string {
  return `${PLACE_IN_NODE_PREFIX}${stepName}`;
}

function placeOutNodeId(stepName: string): string {
  return `${PLACE_OUT_NODE_PREFIX}${stepName}`;
}

function nodeRoleFromId(
  nodeId: string
): "step" | "transition" | "place_in" | "place_out" {
  if (nodeId.startsWith(TRANSITION_NODE_PREFIX)) return "transition";
  if (nodeId.startsWith(PLACE_IN_NODE_PREFIX)) return "place_in";
  if (nodeId.startsWith(PLACE_OUT_NODE_PREFIX)) return "place_out";
  return "step";
}

function stepNameFromNodeId(nodeId: string): string {
  if (nodeId.startsWith(TRANSITION_NODE_PREFIX)) {
    return nodeId.slice(TRANSITION_NODE_PREFIX.length);
  }
  if (nodeId.startsWith(PLACE_IN_NODE_PREFIX)) {
    return nodeId.slice(PLACE_IN_NODE_PREFIX.length);
  }
  if (nodeId.startsWith(PLACE_OUT_NODE_PREFIX)) {
    return nodeId.slice(PLACE_OUT_NODE_PREFIX.length);
  }
  return nodeId;
}

const DESIGNER_NODE_TYPES = {
  dslStep: function DSLStepNode({ data }: NodeProps<Node<DesignerNodeData>>) {
    return (
      <div className={`playbook-designer-node ${data.selected ? "selected" : ""}`}>
        <Handle className="playbook-designer-node__handle" type="target" position={Position.Left} />
        <Handle className="playbook-designer-node__handle" type="source" position={Position.Right} />
        <div className="playbook-designer-node__title">{data.step}</div>
        <div className="playbook-designer-node__kind">{data.kind}</div>
        <div className="playbook-designer-node__desc">
          {(data.desc || "").trim() || "No description"}
        </div>
      </div>
    );
  },
  flowShape: function FlowShapeNode({ data }: NodeProps<Node<DesignerNodeData>>) {
    const shape = data.shape || "process";
    return (
      <div
        className={`playbook-designer-flow-node ${shape} ${data.selected ? "selected" : ""}`}
        title={
          data.playbookRef
            ? `Sub-playbook: ${data.playbookRef} (double-click to drill down)`
            : data.desc || data.step
        }
      >
        <Handle className="playbook-designer-flow-node__handle" type="target" position={Position.Left} />
        <Handle className="playbook-designer-flow-node__handle" type="source" position={Position.Right} />
        <div className="playbook-designer-flow-node__title">{data.step}</div>
        <div className="playbook-designer-flow-node__meta">
          {shape === "subprocess" && data.playbookRef ? `Sub-flow: ${data.playbookRef}` : data.kind}
        </div>
      </div>
    );
  },
  petriTransition: function PetriTransitionNode({ data }: NodeProps<Node<DesignerNodeData>>) {
    return (
      <div className={`playbook-designer-petri-transition ${data.selected ? "selected" : ""}`}>
        <Handle
          className="playbook-designer-petri-transition__handle"
          type="target"
          position={Position.Left}
        />
        <Handle
          className="playbook-designer-petri-transition__handle"
          type="source"
          position={Position.Right}
        />
        <div className="playbook-designer-petri-transition__title">{data.step}</div>
        <div className="playbook-designer-petri-transition__kind">{data.kind}</div>
      </div>
    );
  },
  petriPlace: function PetriPlaceNode({ data }: NodeProps<Node<DesignerNodeData>>) {
    return (
      <div
        className={`playbook-designer-petri-place ${data.selected ? "selected" : ""} ${data.initial ? "initial" : ""} ${data.terminal ? "terminal" : ""}`}
        title={`${data.nodeRole === "place_in" ? "Input" : "Output"} place for ${data.stepRef || data.step}`}
      >
        <Handle
          className="playbook-designer-petri-place__handle"
          type="target"
          position={Position.Left}
        />
        <Handle
          className="playbook-designer-petri-place__handle"
          type="source"
          position={Position.Right}
        />
        {data.initial ? <span className="playbook-designer-petri-place__token" /> : null}
      </div>
    );
  },
};

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function stringifyJson(value: any): string {
  if (value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function parseJsonOrEmpty(text: string, label: string): { value: any; error?: string } {
  if (!text.trim()) return { value: undefined };
  try {
    return { value: JSON.parse(text) };
  } catch (error: any) {
    return { error: `${label}: ${error?.message || "Invalid JSON"}`, value: undefined };
  }
}

function parseJsonObjectOrEmpty(text: string, label: string): { value: AnyRecord | undefined; error?: string } {
  const parsed = parseJsonOrEmpty(text, label);
  if (parsed.error) return parsed;
  if (parsed.value === undefined) return { value: undefined };
  if (typeof parsed.value !== "object" || Array.isArray(parsed.value) || parsed.value === null) {
    return { value: undefined, error: `${label}: must be a JSON object` };
  }
  return { value: parsed.value as AnyRecord };
}

function sanitizeStepName(raw: string): string {
  return (raw || "")
    .trim()
    .replace(/[^a-zA-Z0-9_/-]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function uniqueStepName(base: string, existing: Set<string>, fallbackPrefix = "step"): string {
  let name = sanitizeStepName(base) || fallbackPrefix;
  if (!existing.has(name)) return name;
  let idx = 2;
  while (existing.has(`${name}_${idx}`)) idx += 1;
  return `${name}_${idx}`;
}

function detectStepKind(step: AnyRecord): string {
  const tool = step?.tool;
  if (!tool) return "router";
  if (Array.isArray(tool)) {
    const first = tool[0];
    if (!first) return "pipeline";
    if (typeof first === "object" && first !== null) {
      if (typeof first.kind === "string") return first.kind;
      if (typeof first.name === "string" && typeof first.kind === "string") return first.kind;
      const firstKey = Object.keys(first)[0];
      if (firstKey && first[firstKey] && typeof first[firstKey].kind === "string") return first[firstKey].kind;
    }
    return "pipeline";
  }
  if (typeof tool === "object" && typeof tool.kind === "string") return tool.kind;
  return "step";
}

function extractPlaybookReference(step: AnyRecord): string | null {
  const readPath = (candidate: AnyRecord | undefined): string | null => {
    if (!candidate || typeof candidate !== "object") return null;
    if (String(candidate.kind || "").trim() !== "playbook") return null;
    const pathCandidate =
      candidate.path ?? candidate.playbook ?? candidate.catalog_id ?? candidate.catalogPath;
    if (typeof pathCandidate !== "string") return null;
    const normalized = pathCandidate.trim();
    return normalized || null;
  };

  const tool = step?.tool;
  if (!tool) return null;

  if (Array.isArray(tool)) {
    for (const entry of tool) {
      if (!entry || typeof entry !== "object") continue;
      const direct = readPath(entry as AnyRecord);
      if (direct) return direct;
      const keys = Object.keys(entry);
      if (keys.length === 1) {
        const nested = readPath((entry as AnyRecord)[keys[0]]);
        if (nested) return nested;
      }
    }
    return null;
  }

  if (typeof tool === "object") {
    return readPath(tool as AnyRecord);
  }

  return null;
}

function getExtraStepFields(step: AnyRecord): AnyRecord {
  const extra: AnyRecord = {};
  Object.keys(step || {}).forEach((key) => {
    if (!KNOWN_STEP_KEYS.has(key)) {
      extra[key] = step[key];
    }
  });
  return extra;
}

function makeLayoutStorageKey(pathOrId: string): string {
  return `noetl.playbook.designer.layout.${pathOrId || "new"}`;
}

function loadLayout(storageKey: string): Record<string, { x: number; y: number }> {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed;
  } catch {
    return {};
  }
}

function saveLayout(storageKey: string, positions: Record<string, { x: number; y: number }>): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(positions));
  } catch {
    // Ignore storage errors
  }
}

function defaultNodePosition(index: number): { x: number; y: number } {
  return {
    x: 60 + (index % 3) * 320,
    y: 60 + Math.floor(index / 3) * 180,
  };
}

function normalizeWorkflow(rawWorkflow: any[]): AnyRecord[] {
  const result: AnyRecord[] = [];
  const existing = new Set<string>();

  rawWorkflow.forEach((entry, index) => {
    const stepObj: AnyRecord = entry && typeof entry === "object" ? deepClone(entry) : {};
    const requested = stepObj.step || stepObj.name || `step_${index + 1}`;
    const stepName = uniqueStepName(String(requested), existing);
    existing.add(stepName);
    stepObj.step = stepName;
    result.push(stepObj);
  });

  return result;
}

function defaultRuleDraft(): PipelinePolicyRuleDraft {
  return {
    id: `rule_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    mode: "when",
    when: "{{ outcome.status == 'error' }}",
    do: "retry",
    attempts: "3",
    backoff: "exponential",
    delay: "1",
    to: "",
    setIterText: "",
    setCtxText: "",
  };
}

function normalizeToolToPipelineDraft(tool: any): PipelineTaskDraft[] {
  if (tool === undefined || tool === null) return [];

  const rawTasks: AnyRecord[] = [];
  if (Array.isArray(tool)) {
    tool.forEach((item, idx) => {
      if (!item || typeof item !== "object") return;
      if (typeof item.kind === "string") {
        rawTasks.push({ ...item, name: item.name || `task_${idx + 1}` });
        return;
      }
      const keys = Object.keys(item);
      if (keys.length === 1 && item[keys[0]] && typeof item[keys[0]] === "object") {
        const label = keys[0];
        rawTasks.push({ ...item[label], name: label });
      }
    });
  } else if (typeof tool === "object") {
    if (typeof tool.kind === "string") {
      rawTasks.push({ ...tool, name: tool.name || "task_1" });
    }
  }

  return rawTasks.map((task, idx) => {
    const taskName = String(task.name || `task_${idx + 1}`);
    const taskKind = String(task.kind || "noop");
    const specClone: AnyRecord = task.spec && typeof task.spec === "object" ? deepClone(task.spec) : {};
    const policy = specClone.policy && typeof specClone.policy === "object" ? specClone.policy : {};
    const rules = Array.isArray(policy.rules) ? policy.rules : [];
    if (specClone.policy && typeof specClone.policy === "object") {
      delete specClone.policy.rules;
      if (Object.keys(specClone.policy).length === 0) {
        delete specClone.policy;
      }
    }

    const extraTask: AnyRecord = deepClone(task);
    delete extraTask.name;
    delete extraTask.kind;
    delete extraTask.spec;

    const mappedRules: PipelinePolicyRuleDraft[] = rules.map((rule: AnyRecord, ruleIdx: number) => {
      const id = `rule_${idx}_${ruleIdx}_${Date.now()}`;
      if (rule && typeof rule === "object" && "else" in rule) {
        const thenBlock = rule.else?.then || {};
        return {
          id,
          mode: "else",
          when: "",
          do: String(thenBlock.do || "continue") as TaskAction,
          attempts: thenBlock.attempts !== undefined ? String(thenBlock.attempts) : "",
          backoff: thenBlock.backoff !== undefined ? String(thenBlock.backoff) : "",
          delay: thenBlock.delay !== undefined ? String(thenBlock.delay) : "",
          to: thenBlock.to !== undefined ? String(thenBlock.to) : "",
          setIterText: stringifyJson(thenBlock.set_iter),
          setCtxText: stringifyJson(thenBlock.set_ctx),
        };
      }
      const thenBlock = rule?.then || {};
      return {
        id,
        mode: "when",
        when: String(rule?.when || "{{ true }}"),
        do: String(thenBlock.do || "continue") as TaskAction,
        attempts: thenBlock.attempts !== undefined ? String(thenBlock.attempts) : "",
        backoff: thenBlock.backoff !== undefined ? String(thenBlock.backoff) : "",
        delay: thenBlock.delay !== undefined ? String(thenBlock.delay) : "",
        to: thenBlock.to !== undefined ? String(thenBlock.to) : "",
        setIterText: stringifyJson(thenBlock.set_iter),
        setCtxText: stringifyJson(thenBlock.set_ctx),
      };
    });

    return {
      id: `task_${idx}_${Date.now()}`,
      name: taskName,
      kind: taskKind,
      extraText: stringifyJson(extraTask),
      specText: stringifyJson(specClone),
      rules: mappedRules,
    };
  });
}

function buildToolFromPipelineDraft(
  drafts: PipelineTaskDraft[]
): { value?: AnyRecord[]; error?: string } {
  const tasks: AnyRecord[] = [];

  for (let index = 0; index < drafts.length; index += 1) {
    const draft = drafts[index];
    const taskName = sanitizeStepName(draft.name || `task_${index + 1}`) || `task_${index + 1}`;
    const taskKind = (draft.kind || "noop").trim();
    if (!taskKind) {
      return { error: `Task ${index + 1}: kind is required` };
    }

    const parsedExtra = parseJsonObjectOrEmpty(draft.extraText, `task ${taskName} extra`);
    if (parsedExtra.error) return { error: parsedExtra.error };
    const parsedSpec = parseJsonObjectOrEmpty(draft.specText, `task ${taskName} spec`);
    if (parsedSpec.error) return { error: parsedSpec.error };

    const task: AnyRecord = {
      name: taskName,
      kind: taskKind,
      ...(parsedExtra.value || {}),
    };

    const spec = parsedSpec.value ? deepClone(parsedSpec.value) : {};
    if (!spec.policy || typeof spec.policy !== "object") {
      spec.policy = {};
    }

    const builtRules: AnyRecord[] = [];
    for (let ruleIndex = 0; ruleIndex < draft.rules.length; ruleIndex += 1) {
      const ruleDraft = draft.rules[ruleIndex];
      const thenBlock: AnyRecord = { do: ruleDraft.do };

      if (ruleDraft.attempts.trim()) {
        const parsedAttempts = Number(ruleDraft.attempts);
        if (Number.isNaN(parsedAttempts)) {
          return { error: `Task ${taskName} rule ${ruleIndex + 1}: attempts must be a number` };
        }
        thenBlock.attempts = parsedAttempts;
      }
      if (ruleDraft.backoff.trim()) thenBlock.backoff = ruleDraft.backoff.trim();
      if (ruleDraft.delay.trim()) thenBlock.delay = ruleDraft.delay.trim();
      if (ruleDraft.to.trim()) thenBlock.to = ruleDraft.to.trim();

      const parsedSetIter = parseJsonObjectOrEmpty(
        ruleDraft.setIterText,
        `task ${taskName} rule ${ruleIndex + 1} set_iter`
      );
      if (parsedSetIter.error) return { error: parsedSetIter.error };
      if (parsedSetIter.value !== undefined) thenBlock.set_iter = parsedSetIter.value;

      const parsedSetCtx = parseJsonObjectOrEmpty(
        ruleDraft.setCtxText,
        `task ${taskName} rule ${ruleIndex + 1} set_ctx`
      );
      if (parsedSetCtx.error) return { error: parsedSetCtx.error };
      if (parsedSetCtx.value !== undefined) thenBlock.set_ctx = parsedSetCtx.value;

      if (ruleDraft.mode === "else") {
        builtRules.push({ else: { then: thenBlock } });
      } else {
        if (!ruleDraft.when.trim()) {
          return { error: `Task ${taskName} rule ${ruleIndex + 1}: when is required` };
        }
        builtRules.push({ when: ruleDraft.when.trim(), then: thenBlock });
      }
    }

    if (builtRules.length > 0) {
      spec.policy.rules = builtRules;
    } else if (spec.policy && Object.keys(spec.policy).length === 0) {
      delete spec.policy;
    }

    if (Object.keys(spec).length > 0) {
      task.spec = spec;
    }
    tasks.push(task);
  }

  return { value: tasks };
}

function defaultArcConditionBuilder(): ArcConditionBuilderDraft {
  return {
    left: "ctx.status",
    operator: "==",
    valueType: "string",
    value: "ok",
  };
}

const PlaybookDesigner: React.FC<PlaybookDesignerProps> = ({
  yamlContent,
  onYamlChange,
  playbookId,
  onDrillDownPlaybook,
}) => {
  const [messageApi, messageContext] = message.useMessage();
  const [doc, setDoc] = useState<AnyRecord>(deepClone(DEFAULT_PLAYBOOK_DOC));
  const [workflowSteps, setWorkflowSteps] = useState<AnyRecord[]>([]);
  const [selectedStepName, setSelectedStepName] = useState<string | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [parseError, setParseError] = useState<string | null>(null);
  const [stepDraftError, setStepDraftError] = useState<string | null>(null);
  const [rootDraftError, setRootDraftError] = useState<string | null>(null);
  const [pipelineDraftError, setPipelineDraftError] = useState<string | null>(null);
  const [stepDraft, setStepDraft] = useState<StepDraftState | null>(null);
  const [stepEditorVisible, setStepEditorVisible] = useState(true);
  const [drawerActiveTab, setDrawerActiveTab] = useState("basics");
  const [quickEditorOpen, setQuickEditorOpen] = useState(false);
  const [designerViewMode, setDesignerViewMode] = useState<DesignerViewMode>("flowchart");
  const [showPlaybookInspector, setShowPlaybookInspector] = useState(false);
  const [pipelineDrafts, setPipelineDrafts] = useState<PipelineTaskDraft[]>([]);
  const [arcArgsDrafts, setArcArgsDrafts] = useState<Record<number, string>>({});
  const [arcSpecDrafts, setArcSpecDrafts] = useState<Record<number, string>>({});
  const [arcBuilders, setArcBuilders] = useState<Record<number, ArcConditionBuilderDraft>>({});
  const [arcRowErrors, setArcRowErrors] = useState<Record<number, string>>({});
  const [rootDrafts, setRootDrafts] = useState<RootDraftState>({
    name: "",
    path: "",
    version: "",
    description: "",
    keychainText: "",
    executorText: "",
    workloadText: "",
    workbookText: "",
  });
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [pendingFitView, setPendingFitView] = useState(true);
  const flowInstanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const inspectorRef = useRef<HTMLDivElement | null>(null);
  const lastSerializedYamlRef = useRef<string>("");

  const activeLayoutKey = useMemo(() => {
    const path = doc?.metadata?.path || playbookId || "new";
    return makeLayoutStorageKey(String(path));
  }, [doc?.metadata?.path, playbookId]);

  const commit = useCallback(
    (
      nextDoc: AnyRecord,
      nextSteps: AnyRecord[],
      nextPositions: Record<string, { x: number; y: number }> = positions
    ) => {
      const finalDoc = deepClone(nextDoc);
      finalDoc.workflow = nextSteps;
      const dumped = yaml.dump(finalDoc, {
        noRefs: true,
        lineWidth: 120,
        sortKeys: false,
      });

      lastSerializedYamlRef.current = dumped;
      setDoc(finalDoc);
      setWorkflowSteps(nextSteps);
      setPositions(nextPositions);
      const layoutKey = makeLayoutStorageKey(
        String(finalDoc?.metadata?.path || playbookId || "new")
      );
      saveLayout(layoutKey, nextPositions);
      onYamlChange(dumped);
    },
    [onYamlChange, playbookId, positions]
  );

  useEffect(() => {
    if (yamlContent === lastSerializedYamlRef.current) {
      return;
    }

    if (!yamlContent.trim()) {
      const emptyDoc = deepClone(DEFAULT_PLAYBOOK_DOC);
      setDoc(emptyDoc);
      setWorkflowSteps([]);
      setSelectedStepName(null);
      setPositions({});
      setPendingFitView(true);
      setParseError(null);
      setRootDrafts({
        name: emptyDoc?.metadata?.name || "",
        path: emptyDoc?.metadata?.path || "",
        version: String(emptyDoc?.metadata?.version || ""),
        description: emptyDoc?.metadata?.description || "",
        keychainText: stringifyJson(emptyDoc.keychain),
        executorText: stringifyJson(emptyDoc.executor),
        workloadText: stringifyJson(emptyDoc.workload),
        workbookText: stringifyJson(emptyDoc.workbook),
      });
      return;
    }

    try {
      const loaded = (yaml.load(yamlContent) || {}) as AnyRecord;
      const normalizedDoc = loaded && typeof loaded === "object" ? deepClone(loaded) : {};
      if (!normalizedDoc.apiVersion) normalizedDoc.apiVersion = "noetl.io/v2";
      if (!normalizedDoc.kind) normalizedDoc.kind = "Playbook";
      if (!normalizedDoc.metadata || typeof normalizedDoc.metadata !== "object") normalizedDoc.metadata = {};

      const workflowRaw = Array.isArray(normalizedDoc.workflow) ? normalizedDoc.workflow : [];
      const normalizedSteps = normalizeWorkflow(workflowRaw);
      normalizedDoc.workflow = normalizedSteps;

      const layoutKey = makeLayoutStorageKey(
        String(normalizedDoc?.metadata?.path || playbookId || "new")
      );
      const storedLayout = loadLayout(layoutKey);
      const initialPositions: Record<string, { x: number; y: number }> = {};

      normalizedSteps.forEach((step, index) => {
        initialPositions[step.step] = storedLayout[step.step] || defaultNodePosition(index);
      });

      setDoc(normalizedDoc);
      setWorkflowSteps(normalizedSteps);
      setPositions(initialPositions);
      setPendingFitView(true);
      setSelectedStepName((prev) => {
        if (prev && normalizedSteps.some((step) => step.step === prev)) return prev;
        return normalizedSteps[0]?.step || null;
      });
      setParseError(null);
      setRootDraftError(null);
      setStepDraftError(null);
      setPipelineDraftError(null);
      setArcRowErrors({});
      setRootDrafts({
        name: normalizedDoc?.metadata?.name || "",
        path: normalizedDoc?.metadata?.path || "",
        version: String(normalizedDoc?.metadata?.version || ""),
        description: normalizedDoc?.metadata?.description || "",
        keychainText: stringifyJson(normalizedDoc.keychain),
        executorText: stringifyJson(normalizedDoc.executor),
        workloadText: stringifyJson(normalizedDoc.workload),
        workbookText: stringifyJson(normalizedDoc.workbook),
      });
    } catch (error: any) {
      setParseError(error?.message || "Failed to parse YAML");
    }
  }, [playbookId, yamlContent]);

  useEffect(() => {
    const availableSteps = new Set(workflowSteps.map((step) => step.step));
    const nextEdges: Edge[] = [];
    const inDegree: Record<string, number> = {};
    const outDegree: Record<string, number> = {};
    workflowSteps.forEach((step) => {
      inDegree[step.step] = 0;
      outDegree[step.step] = 0;
    });

    workflowSteps.forEach((step) => {
      const arcs = Array.isArray(step?.next?.arcs) ? step.next.arcs : [];
      outDegree[step.step] = arcs.filter((arc: AnyRecord) => availableSteps.has(arc?.step)).length;
      arcs.forEach((arc: AnyRecord) => {
        const target = arc?.step;
        if (target && availableSteps.has(target)) {
          inDegree[target] = (inDegree[target] || 0) + 1;
        }
      });
    });

    if (designerViewMode === "workflow") {
      const nextNodes: Node[] = workflowSteps.map((step, index) => {
        const pos = positions[step.step] || defaultNodePosition(index);
        const playbookRef = extractPlaybookReference(step);
        return {
          id: step.step,
          type: "dslStep",
          position: pos,
          data: {
            step: step.step,
            stepRef: step.step,
            nodeRole: "step",
            kind: detectStepKind(step),
            desc: step.desc,
            playbookRef: playbookRef || undefined,
            selected: selectedStepName === step.step,
          } satisfies DesignerNodeData,
        };
      });

      workflowSteps.forEach((step) => {
        const arcs = Array.isArray(step?.next?.arcs) ? step.next.arcs : [];
        arcs.forEach((arc: AnyRecord, arcIndex: number) => {
          const target = arc?.step;
          if (!target || !availableSteps.has(target)) return;
          const when = typeof arc.when === "string" ? arc.when : "";
          nextEdges.push({
            id: `${step.step}->${target}#${arcIndex}`,
            source: step.step,
            target,
            label: when && when !== "{{ true }}" ? when : undefined,
            type: "smoothstep",
            style: { stroke: "#5b6b87", strokeWidth: 2 },
            data: {
              kind: "arc",
              sourceStep: step.step,
              targetStep: target,
            },
          });
        });
      });

      setNodes(nextNodes);
      setEdges(nextEdges);
      return;
    }

    if (designerViewMode === "flowchart") {
      const nextNodes: Node[] = workflowSteps.map((step, index) => {
        const pos = positions[step.step] || defaultNodePosition(index);
        const arcs = Array.isArray(step?.next?.arcs) ? step.next.arcs : [];
        const outgoing = arcs.filter((arc: AnyRecord) => availableSteps.has(arc?.step));
        const hasConditionalOutgoing = outgoing.some((arc: AnyRecord) => {
          const when = typeof arc?.when === "string" ? arc.when.trim() : "";
          return !!when && when !== "{{ true }}";
        });
        const playbookRef = extractPlaybookReference(step);

        let shape: DesignerNodeData["shape"] = "process";
        if ((inDegree[step.step] || 0) === 0 || (outDegree[step.step] || 0) === 0) {
          shape = "terminator";
        } else if (outgoing.length > 1 || hasConditionalOutgoing) {
          shape = "decision";
        } else if (playbookRef) {
          shape = "subprocess";
        }

        return {
          id: step.step,
          type: "flowShape",
          position: pos,
          data: {
            step: step.step,
            stepRef: step.step,
            nodeRole: "step",
            kind: detectStepKind(step),
            desc: step.desc,
            shape,
            playbookRef: playbookRef || undefined,
            selected: selectedStepName === step.step,
          } satisfies DesignerNodeData,
        };
      });

      workflowSteps.forEach((step) => {
        const arcs = Array.isArray(step?.next?.arcs) ? step.next.arcs : [];
        arcs.forEach((arc: AnyRecord, arcIndex: number) => {
          const target = arc?.step;
          if (!target || !availableSteps.has(target)) return;
          const when = typeof arc.when === "string" ? arc.when : "";
          nextEdges.push({
            id: `${step.step}->${target}#${arcIndex}`,
            source: step.step,
            target,
            label: when && when !== "{{ true }}" ? when : undefined,
            type: "smoothstep",
            style: { stroke: "#425f84", strokeWidth: 2 },
            data: {
              kind: "arc",
              sourceStep: step.step,
              targetStep: target,
            },
          });
        });
      });

      setNodes(nextNodes);
      setEdges(nextEdges);
      return;
    }

    const nextNodes: Node[] = [];
    workflowSteps.forEach((step, index) => {
      const pos = positions[step.step] || defaultNodePosition(index);
      const inPlaceId = placeInNodeId(step.step);
      const outPlaceId = placeOutNodeId(step.step);
      const transitionId = transitionNodeId(step.step);
      const isSelected = selectedStepName === step.step;
      const playbookRef = extractPlaybookReference(step);

      nextNodes.push({
        id: inPlaceId,
        type: "petriPlace",
        position: { x: pos.x - 44, y: pos.y + 40 },
        data: {
          step: step.step,
          stepRef: step.step,
          nodeRole: "place_in",
          kind: "place",
          selected: isSelected,
          initial: (inDegree[step.step] || 0) === 0,
          terminal: false,
        } satisfies DesignerNodeData,
        draggable: false,
      });

      nextNodes.push({
        id: transitionId,
        type: "petriTransition",
        position: pos,
        data: {
          step: step.step,
          stepRef: step.step,
          nodeRole: "transition",
          kind: detectStepKind(step),
          desc: step.desc,
          playbookRef: playbookRef || undefined,
          selected: isSelected,
        } satisfies DesignerNodeData,
      });

      nextNodes.push({
        id: outPlaceId,
        type: "petriPlace",
        position: { x: pos.x + 260, y: pos.y + 40 },
        data: {
          step: step.step,
          stepRef: step.step,
          nodeRole: "place_out",
          kind: "place",
          selected: isSelected,
          initial: false,
          terminal: (outDegree[step.step] || 0) === 0,
        } satisfies DesignerNodeData,
        draggable: false,
      });

      nextEdges.push({
        id: `${inPlaceId}->${transitionId}`,
        source: inPlaceId,
        target: transitionId,
        type: "smoothstep",
        style: { stroke: "#8aa0bf", strokeWidth: 1.6 },
        deletable: false,
        selectable: false,
        data: {
          kind: "structure",
        },
      });

      nextEdges.push({
        id: `${transitionId}->${outPlaceId}`,
        source: transitionId,
        target: outPlaceId,
        type: "smoothstep",
        style: { stroke: "#8aa0bf", strokeWidth: 1.6 },
        deletable: false,
        selectable: false,
        data: {
          kind: "structure",
        },
      });
    });

    workflowSteps.forEach((step) => {
      const arcs = Array.isArray(step?.next?.arcs) ? step.next.arcs : [];
      arcs.forEach((arc: AnyRecord, arcIndex: number) => {
        const target = arc?.step;
        if (!target || !availableSteps.has(target)) return;
        const when = typeof arc.when === "string" ? arc.when : "";
        nextEdges.push({
          id: `arc:${step.step}->${target}#${arcIndex}`,
          source: placeOutNodeId(step.step),
          target: placeInNodeId(target),
          label: when && when !== "{{ true }}" ? when : undefined,
          type: "smoothstep",
          style: { stroke: "#35507a", strokeWidth: 2 },
          data: {
            kind: "arc",
            sourceStep: step.step,
            targetStep: target,
          },
        });
      });
    });

    setNodes(nextNodes);
    setEdges(nextEdges);
  }, [designerViewMode, positions, selectedStepName, setEdges, setNodes, workflowSteps]);

  useEffect(() => {
    const selected = workflowSteps.find((step) => step.step === selectedStepName);
    if (!selected) {
      setStepDraft(null);
      setPipelineDrafts([]);
      return;
    }
    setStepDraft({
      step: selected.step || "",
      desc: selected.desc || "",
      specText: stringifyJson(selected.spec),
      loopText: stringifyJson(selected.loop),
      toolText: stringifyJson(selected.tool),
      nextText: stringifyJson(selected.next),
      extraText: stringifyJson(getExtraStepFields(selected)),
    });
    setPipelineDrafts(normalizeToolToPipelineDraft(selected.tool));
    setStepDraftError(null);
    setPipelineDraftError(null);
  }, [selectedStepName, workflowSteps]);

  useEffect(() => {
    if (selectedStepName) {
      setShowPlaybookInspector(false);
      setDrawerActiveTab("basics");
    }
  }, [selectedStepName]);

  useEffect(() => {
    if (!selectedStepName) {
      setQuickEditorOpen(false);
    }
  }, [selectedStepName]);

  useEffect(() => {
    setPendingFitView(true);
  }, [designerViewMode]);

  const selectedStep = useMemo(
    () => workflowSteps.find((step) => step.step === selectedStepName),
    [selectedStepName, workflowSteps]
  );

  const selectedPlaybookRef = useMemo(
    () => (selectedStep ? extractPlaybookReference(selectedStep) : null),
    [selectedStep]
  );

  const selectedArcs = useMemo(() => {
    if (!selectedStep) return [];
    return Array.isArray(selectedStep?.next?.arcs) ? selectedStep.next.arcs : [];
  }, [selectedStep]);

  const handleDrillDownReference = useCallback(
    (rawPath?: string | null) => {
      const path = String(rawPath || "").trim();
      if (!path) {
        messageApi.warning("This step does not reference another playbook path");
        return;
      }
      if (!onDrillDownPlaybook) {
        messageApi.info("Drill-down handler is not configured in editor");
        return;
      }
      onDrillDownPlaybook(path);
    },
    [messageApi, onDrillDownPlaybook]
  );

  useEffect(() => {
    const argsDrafts: Record<number, string> = {};
    const specDrafts: Record<number, string> = {};
    const builders: Record<number, ArcConditionBuilderDraft> = {};
    selectedArcs.forEach((arc: AnyRecord, index: number) => {
      argsDrafts[index] = stringifyJson(arc?.args);
      specDrafts[index] = stringifyJson(arc?.spec);
      builders[index] = defaultArcConditionBuilder();
    });
    setArcArgsDrafts(argsDrafts);
    setArcSpecDrafts(specDrafts);
    setArcBuilders(builders);
    setArcRowErrors({});
  }, [selectedArcs]);

  useEffect(() => {
    if (!pendingFitView || !flowInstanceRef.current || nodes.length === 0) return;
    const rafId = window.requestAnimationFrame(() => {
      flowInstanceRef.current?.fitView({ padding: 0.2, duration: 220 });
      setPendingFitView(false);
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [nodes.length, pendingFitView]);

  const handleNodesStateChange = useCallback(
    (changes: NodeChange<Node>[]) => {
      onNodesChange(changes);
      const nextPositions = { ...positions };
      let shouldPersist = false;
      changes.forEach((change) => {
        if (change.type === "position" && change.position) {
          const role = nodeRoleFromId(change.id);
          if (role === "place_in" || role === "place_out") return;
          const stepName = stepNameFromNodeId(change.id);
          nextPositions[stepName] = change.position;
          if ((change as any).dragging !== true) {
            shouldPersist = true;
          }
        }
      });
      if (shouldPersist) {
        setPositions(nextPositions);
        saveLayout(activeLayoutKey, nextPositions);
      }
    },
    [activeLayoutKey, onNodesChange, positions]
  );

  const handleEdgesStateChange = useCallback(
    (changes: EdgeChange<Edge>[]) => {
      const removedIds = changes.filter((c) => c.type === "remove").map((c) => c.id);
      if (removedIds.length) {
        const removedPairs = removedIds
          .map((edgeId) => edges.find((edge) => edge.id === edgeId))
          .filter((edge) => edge && (edge.data as AnyRecord)?.kind === "arc")
          .map((edge) => {
            const edgeData = (edge?.data || {}) as AnyRecord;
            return `${edgeData.sourceStep}::${edgeData.targetStep}`;
          })
          .filter((pair) => !pair.includes("undefined"));

        if (removedPairs.length) {
          const nextSteps = workflowSteps.map((step) => {
            const cloned = deepClone(step);
            const arcs = Array.isArray(cloned?.next?.arcs) ? cloned.next.arcs : [];
            if (arcs.length === 0) return cloned;
            const filtered = arcs.filter(
              (arc: AnyRecord) => !removedPairs.includes(`${cloned.step}::${arc?.step}`)
            );
            if (cloned.next && typeof cloned.next === "object") {
              cloned.next.arcs = filtered;
            }
            return cloned;
          });
          commit(doc, nextSteps, positions);
        }
      }
      onEdgesChange(changes);
    },
    [commit, doc, edges, onEdgesChange, positions, workflowSteps]
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const sourceRole = nodeRoleFromId(connection.source);
      const targetRole = nodeRoleFromId(connection.target);
      const sourceStep =
        sourceRole === "place_in" ? null : stepNameFromNodeId(connection.source);
      const targetStep =
        targetRole === "place_out" ? null : stepNameFromNodeId(connection.target);

      if (!sourceStep || !targetStep) return;
      if (sourceStep === targetStep) return;
      const availableSteps = new Set(workflowSteps.map((step) => step.step));
      if (!availableSteps.has(sourceStep) || !availableSteps.has(targetStep)) return;

      const nextSteps = workflowSteps.map((step) => {
        const cloned = deepClone(step);
        if (cloned.step !== sourceStep) return cloned;

        if (!cloned.next || typeof cloned.next !== "object") {
          cloned.next = { spec: { mode: "exclusive" }, arcs: [] };
        }
        if (!Array.isArray(cloned.next.arcs)) cloned.next.arcs = [];
        const exists = cloned.next.arcs.some((arc: AnyRecord) => arc?.step === targetStep);
        if (!exists) cloned.next.arcs.push({ step: targetStep });
        return cloned;
      });

      commit(doc, nextSteps, positions);
    },
    [commit, doc, positions, workflowSteps]
  );

  const handleAutoLayout = useCallback(() => {
    const nextPositions: Record<string, { x: number; y: number }> = {};
    workflowSteps.forEach((step, idx) => {
      nextPositions[step.step] = defaultNodePosition(idx);
    });
    setPositions(nextPositions);
    saveLayout(activeLayoutKey, nextPositions);
    setPendingFitView(true);
  }, [activeLayoutKey, workflowSteps]);

  const handleResetView = useCallback(() => {
    flowInstanceRef.current?.fitView({ padding: 0.2, duration: 220 });
  }, []);

  const openInlineStepDrawer = useCallback(() => {
    if (!selectedStepName || parseError) return;
    setStepEditorVisible(true);
  }, [parseError, selectedStepName]);

  const focusStepInspector = useCallback(() => {
    setShowPlaybookInspector(false);
    inspectorRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const handleAddStep = useCallback(() => {
    const names = new Set(workflowSteps.map((step) => step.step));
    const stepName = uniqueStepName("new_step", names);
    const nextSteps = [
      ...workflowSteps,
      {
        step: stepName,
        desc: "Describe this step",
        tool: [{ name: "task_1", kind: "noop" }],
      },
    ];
    const nextPositions = { ...positions, [stepName]: defaultNodePosition(nextSteps.length - 1) };
    setSelectedStepName(stepName);
    setShowPlaybookInspector(false);
    setStepEditorVisible(true);
    commit(doc, nextSteps, nextPositions);
  }, [commit, doc, positions, workflowSteps]);

  const handleDeleteSelectedStep = useCallback(() => {
    if (!selectedStepName) return;
    const nextSteps = workflowSteps
      .filter((step) => step.step !== selectedStepName)
      .map((step) => {
        const cloned = deepClone(step);
        const arcs = Array.isArray(cloned?.next?.arcs) ? cloned.next.arcs : [];
        if (arcs.length && cloned.next && typeof cloned.next === "object") {
          cloned.next.arcs = arcs.filter((arc: AnyRecord) => arc?.step !== selectedStepName);
        }
        return cloned;
      });

    const nextPositions = { ...positions };
    delete nextPositions[selectedStepName];

    const nextSelected = nextSteps[0]?.step || null;
    setSelectedStepName(nextSelected);
    commit(doc, nextSteps, nextPositions);
  }, [commit, doc, positions, selectedStepName, workflowSteps]);

  const applyRootDrafts = useCallback(() => {
    const keychain = parseJsonOrEmpty(rootDrafts.keychainText, "keychain");
    const executor = parseJsonOrEmpty(rootDrafts.executorText, "executor");
    const workload = parseJsonOrEmpty(rootDrafts.workloadText, "workload");
    const workbook = parseJsonOrEmpty(rootDrafts.workbookText, "workbook");
    const firstError = keychain.error || executor.error || workload.error || workbook.error;
    if (firstError) {
      setRootDraftError(firstError);
      return;
    }

    const nextDoc = deepClone(doc);
    nextDoc.metadata = nextDoc.metadata || {};
    nextDoc.metadata.name = rootDrafts.name;
    nextDoc.metadata.path = rootDrafts.path;
    nextDoc.metadata.version = rootDrafts.version;
    nextDoc.metadata.description = rootDrafts.description;

    if (keychain.value === undefined) delete nextDoc.keychain;
    else nextDoc.keychain = keychain.value;

    if (executor.value === undefined) delete nextDoc.executor;
    else nextDoc.executor = executor.value;

    if (workload.value === undefined) delete nextDoc.workload;
    else nextDoc.workload = workload.value;

    if (workbook.value === undefined) delete nextDoc.workbook;
    else nextDoc.workbook = workbook.value;

    setRootDraftError(null);
    commit(nextDoc, workflowSteps, positions);
    messageApi.success("Playbook attributes updated");
  }, [commit, doc, messageApi, positions, rootDrafts, workflowSteps]);

  const applyStepDraft = useCallback(() => {
    if (!selectedStepName || !stepDraft) return;

    const selected = workflowSteps.find((step) => step.step === selectedStepName);
    if (!selected) return;

    const existing = new Set(workflowSteps.map((step) => step.step));
    existing.delete(selectedStepName);
    const normalizedName = uniqueStepName(stepDraft.step || selectedStepName, existing);

    const parsedSpec = parseJsonOrEmpty(stepDraft.specText, "spec");
    const parsedLoop = parseJsonOrEmpty(stepDraft.loopText, "loop");
    const parsedTool = parseJsonOrEmpty(stepDraft.toolText, "tool");
    const parsedNext = parseJsonOrEmpty(stepDraft.nextText, "next");
    const parsedExtra = parseJsonOrEmpty(stepDraft.extraText, "extra");
    const firstError =
      parsedSpec.error ||
      parsedLoop.error ||
      parsedTool.error ||
      parsedNext.error ||
      parsedExtra.error;
    if (firstError) {
      setStepDraftError(firstError);
      return;
    }

    if (
      parsedExtra.value !== undefined &&
      (typeof parsedExtra.value !== "object" || Array.isArray(parsedExtra.value))
    ) {
      setStepDraftError("extra must be a JSON object");
      return;
    }

    let nextSteps = workflowSteps.map((step) => {
      const cloned = deepClone(step);
      if (cloned.step !== selectedStepName) {
        if (normalizedName !== selectedStepName && Array.isArray(cloned?.next?.arcs)) {
          cloned.next.arcs = cloned.next.arcs.map((arc: AnyRecord) =>
            arc?.step === selectedStepName ? { ...arc, step: normalizedName } : arc
          );
        }
        return cloned;
      }

      const updated: AnyRecord = {};
      updated.step = normalizedName;
      if (stepDraft.desc.trim()) updated.desc = stepDraft.desc.trim();
      if (parsedSpec.value !== undefined) updated.spec = parsedSpec.value;
      if (parsedLoop.value !== undefined) updated.loop = parsedLoop.value;
      if (parsedTool.value !== undefined) updated.tool = parsedTool.value;
      if (parsedNext.value !== undefined) updated.next = parsedNext.value;
      if (parsedExtra.value && typeof parsedExtra.value === "object") {
        Object.keys(parsedExtra.value).forEach((key) => {
          updated[key] = parsedExtra.value[key];
        });
      }
      return updated;
    });

    if (normalizedName !== selectedStepName) {
      nextSteps = nextSteps.map((step) => {
        const cloned = deepClone(step);
        if (Array.isArray(cloned?.next?.arcs)) {
          cloned.next.arcs = cloned.next.arcs.map((arc: AnyRecord) =>
            arc?.step === selectedStepName ? { ...arc, step: normalizedName } : arc
          );
        }
        return cloned;
      });
    }

    const nextPositions = { ...positions };
    if (normalizedName !== selectedStepName) {
      nextPositions[normalizedName] = nextPositions[selectedStepName] || defaultNodePosition(0);
      delete nextPositions[selectedStepName];
    }

    setSelectedStepName(normalizedName);
    setStepDraftError(null);
    commit(doc, nextSteps, nextPositions);
    messageApi.success("Step updated");
  }, [commit, doc, messageApi, positions, selectedStepName, stepDraft, workflowSteps]);

  const applyPipelineDraft = useCallback(() => {
    if (!selectedStepName) return;

    const built = buildToolFromPipelineDraft(pipelineDrafts);
    if (built.error) {
      setPipelineDraftError(built.error);
      return;
    }

    const nextSteps = workflowSteps.map((step) => {
      if (step.step !== selectedStepName) return deepClone(step);
      const cloned = deepClone(step);
      cloned.tool = built.value || [];
      return cloned;
    });

    setPipelineDraftError(null);
    commit(doc, nextSteps, positions);
    messageApi.success("Canonical task pipeline updated");
  }, [commit, doc, messageApi, pipelineDrafts, positions, selectedStepName, workflowSteps]);

  const updateSelectedStepArcs = useCallback(
    (nextArcs: AnyRecord[]) => {
      if (!selectedStepName) return;
      const nextSteps = workflowSteps.map((step) => {
        if (step.step !== selectedStepName) return deepClone(step);
        const cloned = deepClone(step);
        if (!cloned.next || typeof cloned.next !== "object") {
          cloned.next = { spec: { mode: "exclusive" } };
        }
        cloned.next.arcs = nextArcs;
        return cloned;
      });
      commit(doc, nextSteps, positions);
    },
    [commit, doc, positions, selectedStepName, workflowSteps]
  );

  const addArcFromInspector = useCallback(() => {
    if (!selectedStepName) return;
    const target = workflowSteps.find((step) => step.step !== selectedStepName)?.step;
    if (!target) return;
    updateSelectedStepArcs([...selectedArcs, { step: target }]);
  }, [selectedArcs, selectedStepName, updateSelectedStepArcs, workflowSteps]);

  const applyArcAdvanced = (index: number) => {
    const parsedArgs = parseJsonObjectOrEmpty(arcArgsDrafts[index] || "", "arc.args");
    if (parsedArgs.error) {
      setArcRowErrors((prev) => ({ ...prev, [index]: parsedArgs.error as string }));
      return;
    }
    const parsedSpec = parseJsonObjectOrEmpty(arcSpecDrafts[index] || "", "arc.spec");
    if (parsedSpec.error) {
      setArcRowErrors((prev) => ({ ...prev, [index]: parsedSpec.error as string }));
      return;
    }

    const nextArcs = deepClone(selectedArcs);
    if (!nextArcs[index]) return;
    if (parsedArgs.value === undefined) delete nextArcs[index].args;
    else nextArcs[index].args = parsedArgs.value;
    if (parsedSpec.value === undefined) delete nextArcs[index].spec;
    else nextArcs[index].spec = parsedSpec.value;
    setArcRowErrors((prev) => ({ ...prev, [index]: "" }));
    updateSelectedStepArcs(nextArcs);
  };

  const buildArcWhenFromBuilder = (index: number) => {
    const builder = arcBuilders[index] || defaultArcConditionBuilder();
    let rhs = "null";
    if (builder.valueType === "string") rhs = JSON.stringify(builder.value || "");
    if (builder.valueType === "number") rhs = String(Number(builder.value || 0));
    if (builder.valueType === "boolean") rhs = builder.value === "true" ? "true" : "false";
    if (builder.valueType === "null") rhs = "none";

    let expression = "";
    if (builder.operator === "contains") {
      expression = `{{ ${rhs} in ${builder.left || "ctx"} }}`;
    } else {
      expression = `{{ ${builder.left || "ctx"} ${builder.operator} ${rhs} }}`;
    }

    const nextArcs = deepClone(selectedArcs);
    if (!nextArcs[index]) return;
    nextArcs[index].when = expression;
    updateSelectedStepArcs(nextArcs);
  };

  const addPipelineTask = () => {
    setPipelineDrafts((prev) => [
      ...prev,
      {
        id: `task_${Date.now()}`,
        name: `task_${prev.length + 1}`,
        kind: "noop",
        extraText: "",
        specText: "",
        rules: [],
      },
    ]);
  };

  const toComparablePipeline = useCallback(
    (drafts: PipelineTaskDraft[]) =>
      drafts.map((task) => ({
        name: task.name || "",
        kind: task.kind || "",
        extraText: task.extraText || "",
        specText: task.specText || "",
        rules: (task.rules || []).map((rule) => ({
          mode: rule.mode,
          when: rule.when || "",
          do: rule.do,
          attempts: rule.attempts || "",
          backoff: rule.backoff || "",
          delay: rule.delay || "",
          to: rule.to || "",
          setIterText: rule.setIterText || "",
          setCtxText: rule.setCtxText || "",
        })),
      })),
    []
  );

  const baselinePipelineDrafts = useMemo(
    () => normalizeToolToPipelineDraft(selectedStep?.tool),
    [selectedStep?.tool]
  );

  const stepBasicsDirty = useMemo(() => {
    if (!selectedStep || !stepDraft) return false;
    return (
      (stepDraft.step || "") !== String(selectedStep.step || "") ||
      (stepDraft.desc || "") !== String(selectedStep.desc || "") ||
      (stepDraft.specText || "") !== stringifyJson(selectedStep.spec) ||
      (stepDraft.loopText || "") !== stringifyJson(selectedStep.loop) ||
      (stepDraft.extraText || "") !== stringifyJson(getExtraStepFields(selectedStep))
    );
  }, [selectedStep, stepDraft]);

  const stepRawDirty = useMemo(() => {
    if (!selectedStep || !stepDraft) return false;
    return (
      (stepDraft.toolText || "") !== stringifyJson(selectedStep.tool) ||
      (stepDraft.nextText || "") !== stringifyJson(selectedStep.next)
    );
  }, [selectedStep, stepDraft]);

  const tasksDirty = useMemo(() => {
    const current = toComparablePipeline(pipelineDrafts).map((task) => ({
      name: task.name,
      kind: task.kind,
      extraText: task.extraText,
      specText: task.specText,
    }));
    const baseline = toComparablePipeline(baselinePipelineDrafts).map((task) => ({
      name: task.name,
      kind: task.kind,
      extraText: task.extraText,
      specText: task.specText,
    }));
    return JSON.stringify(current) !== JSON.stringify(baseline);
  }, [baselinePipelineDrafts, pipelineDrafts, toComparablePipeline]);

  const policyDirty = useMemo(() => {
    const current = toComparablePipeline(pipelineDrafts).map((task) => task.rules);
    const baseline = toComparablePipeline(baselinePipelineDrafts).map((task) => task.rules);
    return JSON.stringify(current) !== JSON.stringify(baseline);
  }, [baselinePipelineDrafts, pipelineDrafts, toComparablePipeline]);

  const arcsDirty = useMemo(
    () =>
      selectedArcs.some(
        (arc: AnyRecord, index: number) =>
          (arcArgsDrafts[index] || "") !== stringifyJson(arc?.args) ||
          (arcSpecDrafts[index] || "") !== stringifyJson(arc?.spec)
      ),
    [arcArgsDrafts, arcSpecDrafts, selectedArcs]
  );

  const stepAnyDirty = stepBasicsDirty || stepRawDirty;
  const pipelineAnyDirty = tasksDirty || policyDirty;

  const renderDirtyTabLabel = (title: string, dirty: boolean) => (
    <span className="playbook-designer__tab-label">
      {title}
      {dirty ? <span className="playbook-designer__dirty-dot" /> : null}
    </span>
  );

  const renderStepSelector = () => (
    <div className="playbook-designer__block">
      <Text type="secondary">Selected Step</Text>
      <Select
        value={selectedStepName || undefined}
        style={{ width: "100%" }}
        onChange={(value) => {
          setSelectedStepName(value);
          setShowPlaybookInspector(false);
        }}
        options={workflowSteps.map((step) => ({ value: step.step, label: step.step }))}
        placeholder="Select step"
      />
    </div>
  );

  const renderStepBasicsSection = () => {
    if (!stepDraft) {
      return <Alert type="info" showIcon message="Select or add a step to edit DSL attributes." />;
    }

    return (
      <>
        <Row gutter={8}>
          <Col span={12}>
            <Text type="secondary">step</Text>
            <Input
              value={stepDraft.step}
              onChange={(e) =>
                setStepDraft((prev) => (prev ? { ...prev, step: e.target.value } : prev))
              }
            />
          </Col>
          <Col span={12}>
            <Text type="secondary">desc</Text>
            <Input
              value={stepDraft.desc}
              onChange={(e) =>
                setStepDraft((prev) => (prev ? { ...prev, desc: e.target.value } : prev))
              }
            />
          </Col>
        </Row>

        <div className="playbook-designer__block">
          <Text type="secondary">spec (JSON)</Text>
          <Input.TextArea
            rows={4}
            value={stepDraft.specText}
            onChange={(e) =>
              setStepDraft((prev) => (prev ? { ...prev, specText: e.target.value } : prev))
            }
          />
        </div>

        <div className="playbook-designer__block">
          <Text type="secondary">loop (JSON)</Text>
          <Input.TextArea
            rows={4}
            value={stepDraft.loopText}
            onChange={(e) =>
              setStepDraft((prev) => (prev ? { ...prev, loopText: e.target.value } : prev))
            }
          />
        </div>

        <div className="playbook-designer__block">
          <Text type="secondary">Extra Step Fields (JSON object)</Text>
          <Input.TextArea
            rows={3}
            value={stepDraft.extraText}
            onChange={(e) =>
              setStepDraft((prev) => (prev ? { ...prev, extraText: e.target.value } : prev))
            }
          />
        </div>
      </>
    );
  };

  const renderPipelineSection = ({
    showTaskFields,
    showRules,
    showAddTaskButton,
    showApplyButton,
    showError,
  }: {
    showTaskFields: boolean;
    showRules: boolean;
    showAddTaskButton: boolean;
    showApplyButton: boolean;
    showError: boolean;
  }) => (
    <Space direction="vertical" style={{ width: "100%" }} size={10}>
      {pipelineDrafts.map((task, taskIndex) => (
        <Card
          key={task.id}
          size="small"
          className="playbook-designer__pipeline-task-card"
          title={
            <Space>
              <Text strong>{task.name || `Task ${taskIndex + 1}`}</Text>
              <Tag color="blue">{task.kind || "noop"}</Tag>
            </Space>
          }
          extra={
            <Button
              danger
              icon={<DeleteOutlined />}
              onClick={() =>
                setPipelineDrafts((prev) => prev.filter((item) => item.id !== task.id))
              }
            />
          }
        >
          {showTaskFields ? (
            <>
              <Row gutter={8}>
                <Col span={12}>
                  <Text type="secondary">Task Name</Text>
                  <Input
                    value={task.name}
                    onChange={(e) =>
                      setPipelineDrafts((prev) =>
                        prev.map((item) =>
                          item.id === task.id ? { ...item, name: e.target.value } : item
                        )
                      )
                    }
                  />
                </Col>
                <Col span={12}>
                  <Text type="secondary">kind</Text>
                  <Select
                    value={task.kind}
                    style={{ width: "100%" }}
                    onChange={(value) =>
                      setPipelineDrafts((prev) =>
                        prev.map((item) =>
                          item.id === task.id ? { ...item, kind: value } : item
                        )
                      )
                    }
                    options={COMMON_TOOL_KINDS.map((kind) => ({ value: kind, label: kind }))}
                  />
                </Col>
              </Row>

              <div className="playbook-designer__block">
                <Text type="secondary">Task Fields (JSON object)</Text>
                <Input.TextArea
                  rows={4}
                  value={task.extraText}
                  onChange={(e) =>
                    setPipelineDrafts((prev) =>
                      prev.map((item) =>
                        item.id === task.id ? { ...item, extraText: e.target.value } : item
                      )
                    )
                  }
                  placeholder='{"method":"GET","url":"{{ workload.api_url }}"}'
                />
              </div>

              <div className="playbook-designer__block">
                <Text type="secondary">Task spec without policy.rules (JSON object)</Text>
                <Input.TextArea
                  rows={3}
                  value={task.specText}
                  onChange={(e) =>
                    setPipelineDrafts((prev) =>
                      prev.map((item) =>
                        item.id === task.id ? { ...item, specText: e.target.value } : item
                      )
                    )
                  }
                  placeholder='{"timeout":{"read":10}}'
                />
              </div>
            </>
          ) : null}

          {showRules ? (
            <>
              <Divider className="playbook-designer__divider">policy.rules</Divider>
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {task.rules.map((rule) => (
                  <Card key={rule.id} size="small" className="playbook-designer__rule-card">
                    <Row gutter={8}>
                      <Col span={6}>
                        <Text type="secondary">mode</Text>
                        <Select
                          value={rule.mode}
                          style={{ width: "100%" }}
                          options={[
                            { value: "when", label: "when" },
                            { value: "else", label: "else" },
                          ]}
                          onChange={(value) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, mode: value } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                      <Col span={18}>
                        <Text type="secondary">when</Text>
                        <Input
                          disabled={rule.mode === "else"}
                          value={rule.when}
                          placeholder="{{ outcome.status == 'ok' }}"
                          onChange={(e) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, when: e.target.value } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                    </Row>

                    <Row gutter={8} className="playbook-designer__rule-grid">
                      <Col span={8}>
                        <Text type="secondary">then.do</Text>
                        <Select
                          value={rule.do}
                          style={{ width: "100%" }}
                          options={[
                            { value: "continue", label: "continue" },
                            { value: "retry", label: "retry" },
                            { value: "jump", label: "jump" },
                            { value: "break", label: "break" },
                            { value: "fail", label: "fail" },
                          ]}
                          onChange={(value) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, do: value } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                      <Col span={4}>
                        <Text type="secondary">attempts</Text>
                        <InputNumber
                          style={{ width: "100%" }}
                          value={rule.attempts ? Number(rule.attempts) : undefined}
                          onChange={(value) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id
                                          ? { ...r, attempts: value !== null ? String(value) : "" }
                                          : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                      <Col span={6}>
                        <Text type="secondary">backoff</Text>
                        <Select
                          allowClear
                          value={rule.backoff || undefined}
                          style={{ width: "100%" }}
                          options={[
                            { value: "none", label: "none" },
                            { value: "linear", label: "linear" },
                            { value: "exponential", label: "exponential" },
                          ]}
                          onChange={(value) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, backoff: value || "" } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                      <Col span={6}>
                        <Text type="secondary">delay / to</Text>
                        <Input
                          value={rule.do === "jump" ? rule.to : rule.delay}
                          placeholder={rule.do === "jump" ? "target task" : "seconds"}
                          onChange={(e) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id
                                          ? rule.do === "jump"
                                            ? { ...r, to: e.target.value }
                                            : { ...r, delay: e.target.value }
                                          : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                    </Row>

                    <Row gutter={8} className="playbook-designer__rule-grid">
                      <Col span={12}>
                        <Text type="secondary">set_iter (JSON object)</Text>
                        <Input.TextArea
                          rows={2}
                          value={rule.setIterText}
                          onChange={(e) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, setIterText: e.target.value } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                      <Col span={12}>
                        <Text type="secondary">set_ctx (JSON object)</Text>
                        <Input.TextArea
                          rows={2}
                          value={rule.setCtxText}
                          onChange={(e) =>
                            setPipelineDrafts((prev) =>
                              prev.map((item) =>
                                item.id === task.id
                                  ? {
                                      ...item,
                                      rules: item.rules.map((r) =>
                                        r.id === rule.id ? { ...r, setCtxText: e.target.value } : r
                                      ),
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </Col>
                    </Row>

                    <Button
                      danger
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={() =>
                        setPipelineDrafts((prev) =>
                          prev.map((item) =>
                            item.id === task.id
                              ? {
                                  ...item,
                                  rules: item.rules.filter((r) => r.id !== rule.id),
                                }
                              : item
                          )
                        )
                      }
                    >
                      Remove Rule
                    </Button>
                  </Card>
                ))}

                <Button
                  size="small"
                  onClick={() =>
                    setPipelineDrafts((prev) =>
                      prev.map((item) =>
                        item.id === task.id
                          ? { ...item, rules: [...item.rules, defaultRuleDraft()] }
                          : item
                      )
                    )
                  }
                >
                  Add Policy Rule
                </Button>
              </Space>
            </>
          ) : null}
        </Card>
      ))}

      {showAddTaskButton || showApplyButton ? (
        <Space>
          {showAddTaskButton ? (
            <Button icon={<PlusOutlined />} onClick={addPipelineTask}>
              Add Task
            </Button>
          ) : null}
          {showApplyButton ? (
            <Button type="primary" icon={<SaveOutlined />} onClick={applyPipelineDraft}>
              Apply Pipeline
            </Button>
          ) : null}
        </Space>
      ) : null}

      {showError && pipelineDraftError ? <Alert type="error" showIcon message={pipelineDraftError} /> : null}
    </Space>
  );

  const renderArcsSection = () => (
    <Space direction="vertical" style={{ width: "100%" }} size={8}>
      {selectedArcs.map((arc: AnyRecord, index: number) => (
        <Card
          key={`${selectedStepName}-arc-${index}`}
          size="small"
          className="playbook-designer__arc-card"
          title={`Arc ${index + 1}`}
          extra={
            <Button
              danger
              icon={<DeleteOutlined />}
              onClick={() => {
                const nextArcs = selectedArcs.filter((_: AnyRecord, idx: number) => idx !== index);
                updateSelectedStepArcs(nextArcs);
              }}
            />
          }
        >
          <div className="playbook-designer__arc-row">
            <Select
              value={arc?.step}
              style={{ width: "100%" }}
              options={workflowSteps
                .filter((step) => step.step !== selectedStepName)
                .map((step) => ({ value: step.step, label: step.step }))}
              onChange={(target) => {
                const nextArcs = deepClone(selectedArcs);
                nextArcs[index] = { ...nextArcs[index], step: target };
                updateSelectedStepArcs(nextArcs);
              }}
            />
            <Input
              value={arc?.when || ""}
              placeholder="{{ true }}"
              onChange={(event) => {
                const nextArcs = deepClone(selectedArcs);
                nextArcs[index] = { ...nextArcs[index], when: event.target.value };
                updateSelectedStepArcs(nextArcs);
              }}
            />
          </div>

          <div className="playbook-designer__arc-builder-row">
            <Select
              value={arcBuilders[index]?.left}
              style={{ width: "100%" }}
              options={[
                "ctx.status",
                "ctx.user_role",
                "workload.env",
                "event.status",
                "event.type",
                "args.source",
              ].map((value) => ({ value, label: value }))}
              onChange={(value) =>
                setArcBuilders((prev) => ({
                  ...prev,
                  [index]: { ...(prev[index] || defaultArcConditionBuilder()), left: value },
                }))
              }
            />
            <Select
              value={arcBuilders[index]?.operator}
              style={{ width: "100%" }}
              options={[
                { value: "==", label: "==" },
                { value: "!=", label: "!=" },
                { value: ">", label: ">" },
                { value: ">=", label: ">=" },
                { value: "<", label: "<" },
                { value: "<=", label: "<=" },
                { value: "contains", label: "contains" },
              ]}
              onChange={(value) =>
                setArcBuilders((prev) => ({
                  ...prev,
                  [index]: {
                    ...(prev[index] || defaultArcConditionBuilder()),
                    operator: value,
                  },
                }))
              }
            />
            <Select
              value={arcBuilders[index]?.valueType}
              style={{ width: "100%" }}
              options={[
                { value: "string", label: "string" },
                { value: "number", label: "number" },
                { value: "boolean", label: "boolean" },
                { value: "null", label: "null" },
              ]}
              onChange={(value) =>
                setArcBuilders((prev) => ({
                  ...prev,
                  [index]: {
                    ...(prev[index] || defaultArcConditionBuilder()),
                    valueType: value,
                  },
                }))
              }
            />
            <Input
              value={arcBuilders[index]?.value}
              placeholder="value"
              onChange={(event) =>
                setArcBuilders((prev) => ({
                  ...prev,
                  [index]: {
                    ...(prev[index] || defaultArcConditionBuilder()),
                    value: event.target.value,
                  },
                }))
              }
            />
            <Button onClick={() => buildArcWhenFromBuilder(index)}>Build when</Button>
          </div>

          <div className="playbook-designer__block">
            <Text type="secondary">args (JSON object)</Text>
            <Input.TextArea
              rows={3}
              value={arcArgsDrafts[index] || ""}
              onChange={(event) =>
                setArcArgsDrafts((prev) => ({
                  ...prev,
                  [index]: event.target.value,
                }))
              }
              placeholder='{"source":"manual"}'
            />
          </div>
          <div className="playbook-designer__block">
            <Text type="secondary">spec (JSON object)</Text>
            <Input.TextArea
              rows={3}
              value={arcSpecDrafts[index] || ""}
              onChange={(event) =>
                setArcSpecDrafts((prev) => ({
                  ...prev,
                  [index]: event.target.value,
                }))
              }
              placeholder='{"priority":10}'
            />
          </div>

          <Button size="small" type="primary" onClick={() => applyArcAdvanced(index)}>
            Apply Arc args/spec
          </Button>
          {arcRowErrors[index] ? (
            <Alert
              className="playbook-designer__block"
              type="error"
              showIcon
              message={arcRowErrors[index]}
            />
          ) : null}
        </Card>
      ))}
      <Button onClick={addArcFromInspector}>Add Arc</Button>
    </Space>
  );

  const renderRawSection = () => {
    if (!stepDraft) return null;

    return (
      <>
        <div className="playbook-designer__block">
          <Text type="secondary">tool (JSON)</Text>
          <Input.TextArea
            rows={5}
            value={stepDraft.toolText}
            onChange={(e) =>
              setStepDraft((prev) => (prev ? { ...prev, toolText: e.target.value } : prev))
            }
          />
        </div>
        <div className="playbook-designer__block">
          <Text type="secondary">next (JSON)</Text>
          <Input.TextArea
            rows={4}
            value={stepDraft.nextText}
            onChange={(e) =>
              setStepDraft((prev) => (prev ? { ...prev, nextText: e.target.value } : prev))
            }
          />
        </div>
      </>
    );
  };

  const renderStepEditorContent = (mode: "inspector" | "drawer" = "inspector") => (
    <>
      {renderStepSelector()}

      {!stepDraft ? (
        <Alert type="info" showIcon message="Select or add a step to edit DSL attributes." />
      ) : mode === "drawer" ? (
        <Tabs
          activeKey={drawerActiveTab}
          onChange={setDrawerActiveTab}
          items={[
            {
              key: "basics",
              label: renderDirtyTabLabel("Basics", stepBasicsDirty),
              children: renderStepBasicsSection(),
            },
            {
              key: "tasks",
              label: renderDirtyTabLabel("Tasks", tasksDirty),
              children: renderPipelineSection({
                showTaskFields: true,
                showRules: false,
                showAddTaskButton: true,
                showApplyButton: false,
                showError: false,
              }),
            },
            {
              key: "policy",
              label: renderDirtyTabLabel("Policy", policyDirty),
              children: renderPipelineSection({
                showTaskFields: false,
                showRules: true,
                showAddTaskButton: false,
                showApplyButton: false,
                showError: true,
              }),
            },
            {
              key: "arcs",
              label: renderDirtyTabLabel("Arcs", arcsDirty),
              children: renderArcsSection(),
            },
            {
              key: "raw",
              label: renderDirtyTabLabel("Raw", stepRawDirty),
              children: renderRawSection(),
            },
          ]}
        />
      ) : (
        <>
          {renderStepBasicsSection()}

          <Divider className="playbook-designer__divider">Canonical Task Pipeline</Divider>
          {renderPipelineSection({
            showTaskFields: true,
            showRules: true,
            showAddTaskButton: true,
            showApplyButton: true,
            showError: true,
          })}

          <Divider className="playbook-designer__divider">Arc Editor</Divider>
          {renderArcsSection()}

          <Divider className="playbook-designer__divider">Raw Step JSON Fields</Divider>
          {renderRawSection()}

          {stepDraftError && <Alert type="error" showIcon message={stepDraftError} />}
          <Button type="primary" icon={<SaveOutlined />} onClick={applyStepDraft}>
            Apply Step Attributes
          </Button>
        </>
      )}
    </>
  );

  return (
    <div className="playbook-designer">
      {messageContext}
      {parseError && (
        <Alert
          type="warning"
          showIcon
          message="Designer is read-only while YAML is invalid"
          description={parseError}
          className="playbook-designer__alert"
        />
      )}

      <div className="playbook-designer__toolbar">
        <Space>
          <Button icon={<PlusOutlined />} onClick={handleAddStep} disabled={!!parseError}>
            Add Step
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleAutoLayout}>
            Auto Layout
          </Button>
          <Button icon={<AimOutlined />} onClick={handleResetView}>
            Reset View
          </Button>
          <Button
            icon={<EditOutlined />}
            disabled={!selectedStepName || !!parseError}
            onClick={() => {
              if (stepEditorVisible) {
                setStepEditorVisible(false);
                return;
              }
              openInlineStepDrawer();
              focusStepInspector();
            }}
          >
            {stepEditorVisible ? "Hide Step Editor" : "Show Step Editor"}
          </Button>
          <Button
            icon={<ApartmentOutlined />}
            disabled={!selectedStepName || !!parseError}
            onClick={() => setQuickEditorOpen((prev) => !prev)}
          >
            {quickEditorOpen ? "Hide Quick Edit" : "Quick Edit"}
          </Button>
          <Popconfirm
            title="Delete selected step?"
            okText="Delete"
            okButtonProps={{ danger: true }}
            disabled={!selectedStepName}
            onConfirm={handleDeleteSelectedStep}
          >
            <Button danger icon={<DeleteOutlined />} disabled={!selectedStepName || !!parseError}>
              Delete Step
            </Button>
          </Popconfirm>
        </Space>
        <Space>
          <Select
            size="small"
            value={designerViewMode}
            style={{ width: 190 }}
            onChange={(value) => setDesignerViewMode(value as DesignerViewMode)}
            options={[
              { value: "workflow", label: "Workflow Blocks" },
              { value: "flowchart", label: "Workflow Diagram" },
              { value: "petri", label: "Petri Net View" },
            ]}
          />
          <Tag color="blue">{workflowSteps.length} steps</Tag>
          <Text type="secondary">
            {designerViewMode === "petri"
              ? "Petri mode: transitions are steps, circles are places, and arc conditions label place-to-place links."
              : designerViewMode === "flowchart"
              ? "Diagram mode: flowchart-style shapes (terminators, decisions, subprocess blocks) with direct drill-down for playbook references."
              : "Click a step to focus it. Use the Step Editor toggle to show or hide the full editor panel."}
          </Text>
        </Space>
      </div>

      <div className="playbook-designer__layout">
        <div className="playbook-designer__canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={DESIGNER_NODE_TYPES}
            onNodesChange={handleNodesStateChange}
            onEdgesChange={handleEdgesStateChange}
            onNodeClick={(_, node) => {
              const nodeData = (node.data || {}) as AnyRecord;
              const stepRef =
                typeof nodeData.stepRef === "string" ? nodeData.stepRef : stepNameFromNodeId(node.id);
              const role =
                typeof nodeData.nodeRole === "string"
                  ? nodeData.nodeRole
                  : nodeRoleFromId(node.id);
              if (!workflowSteps.some((step) => step.step === stepRef)) {
                return;
              }
              setSelectedStepName(stepRef);
              setShowPlaybookInspector(false);
              if (role !== "place_in" && role !== "place_out") {
                setStepEditorVisible(true);
              }
            }}
            onNodeDoubleClick={(_, node) => {
              const nodeData = (node.data || {}) as AnyRecord;
              const stepRef =
                typeof nodeData.stepRef === "string" ? nodeData.stepRef : stepNameFromNodeId(node.id);
              const playbookRef =
                typeof nodeData.playbookRef === "string" ? nodeData.playbookRef : null;
              if (!workflowSteps.some((step) => step.step === stepRef)) {
                return;
              }
              setSelectedStepName(stepRef);
              if (playbookRef) {
                handleDrillDownReference(playbookRef);
                return;
              }
              setShowPlaybookInspector(false);
              setStepEditorVisible(true);
            }}
            onConnect={handleConnect}
            onInit={(instance) => {
              flowInstanceRef.current = instance;
              setPendingFitView(true);
            }}
            minZoom={0.35}
            maxZoom={2.2}
            onlyRenderVisibleElements={false}
            defaultEdgeOptions={{ type: "smoothstep", style: { stroke: "#5b6b87", strokeWidth: 2 } }}
          >
            <Controls />
            <MiniMap pannable zoomable />
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#d8dee8" />
          </ReactFlow>
          {stepDraft && !parseError && quickEditorOpen ? (
            <Card size="small" className="playbook-designer__quick-editor">
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
                  <Text strong>Step Quick Edit</Text>
                  <Space size={6}>
                    <Tag color="blue">{selectedStepName}</Tag>
                    <Button
                      size="small"
                      type="text"
                      icon={<CloseOutlined />}
                      onClick={() => setQuickEditorOpen(false)}
                      aria-label="Close quick editor"
                    />
                  </Space>
                </Space>
                <Input
                  placeholder="step"
                  value={stepDraft.step}
                  onChange={(event) =>
                    setStepDraft((prev) => (prev ? { ...prev, step: event.target.value } : prev))
                  }
                />
                <Input
                  placeholder="desc"
                  value={stepDraft.desc}
                  onChange={(event) =>
                    setStepDraft((prev) => (prev ? { ...prev, desc: event.target.value } : prev))
                  }
                />
                <Space style={{ width: "100%", justifyContent: "space-between" }}>
                  <Button size="small" icon={<SettingOutlined />} onClick={openInlineStepDrawer}>
                    Advanced
                  </Button>
                  <Button size="small" type="primary" icon={<SaveOutlined />} onClick={applyStepDraft}>
                    Save Step
                  </Button>
                </Space>
              </Space>
            </Card>
          ) : null}
        </div>

        <div className="playbook-designer__inspector" ref={inspectorRef}>
          <Card size="small" className="playbook-designer__card playbook-designer__card--playbook">
            <Title level={5} className="playbook-designer__card-title">
              <Space>
                <SettingOutlined />
                Playbook Attributes
              </Space>
            </Title>
            <div className="playbook-designer__playbook-toggle">
              <Button size="small" onClick={() => setShowPlaybookInspector((prev) => !prev)}>
                {showPlaybookInspector ? "Hide Playbook Fields" : "Show Playbook Fields"}
              </Button>
            </div>
            {!showPlaybookInspector ? (
              <Alert
                type="info"
                showIcon
                message="Playbook fields are hidden while you design steps."
              />
            ) : (
              <>
                <Row gutter={8}>
              <Col span={12}>
                <Text type="secondary">Metadata Name</Text>
                <Input
                  value={rootDrafts.name}
                  onChange={(e) => setRootDrafts((prev) => ({ ...prev, name: e.target.value }))}
                />
              </Col>
              <Col span={12}>
                <Text type="secondary">Metadata Version</Text>
                <Input
                  value={rootDrafts.version}
                  onChange={(e) => setRootDrafts((prev) => ({ ...prev, version: e.target.value }))}
                />
              </Col>
            </Row>
            <div className="playbook-designer__block">
              <Text type="secondary">Metadata Path</Text>
              <Input
                value={rootDrafts.path}
                onChange={(e) => setRootDrafts((prev) => ({ ...prev, path: e.target.value }))}
              />
            </div>
            <div className="playbook-designer__block">
              <Text type="secondary">Metadata Description</Text>
              <Input.TextArea
                rows={2}
                value={rootDrafts.description}
                onChange={(e) =>
                  setRootDrafts((prev) => ({ ...prev, description: e.target.value }))
                }
              />
            </div>

            <Divider className="playbook-designer__divider">Root JSON Fields</Divider>
            <div className="playbook-designer__block">
              <Text type="secondary">keychain</Text>
              <Input.TextArea
                rows={3}
                value={rootDrafts.keychainText}
                onChange={(e) =>
                  setRootDrafts((prev) => ({ ...prev, keychainText: e.target.value }))
                }
              />
            </div>
            <div className="playbook-designer__block">
              <Text type="secondary">executor</Text>
              <Input.TextArea
                rows={3}
                value={rootDrafts.executorText}
                onChange={(e) =>
                  setRootDrafts((prev) => ({ ...prev, executorText: e.target.value }))
                }
              />
            </div>
            <div className="playbook-designer__block">
              <Text type="secondary">workload</Text>
              <Input.TextArea
                rows={3}
                value={rootDrafts.workloadText}
                onChange={(e) =>
                  setRootDrafts((prev) => ({ ...prev, workloadText: e.target.value }))
                }
              />
            </div>
            <div className="playbook-designer__block">
              <Text type="secondary">workbook</Text>
              <Input.TextArea
                rows={3}
                value={rootDrafts.workbookText}
                onChange={(e) =>
                  setRootDrafts((prev) => ({ ...prev, workbookText: e.target.value }))
                }
              />
            </div>
            {rootDraftError && <Alert type="error" showIcon message={rootDraftError} />}
            <Button type="primary" icon={<SaveOutlined />} onClick={applyRootDrafts}>
              Apply Playbook Attributes
            </Button>
              </>
            )}
          </Card>

          <Card size="small" className="playbook-designer__card playbook-designer__card--step">
            <div className="playbook-designer__step-header">
              <Space className="playbook-designer__card-heading" align="center">
                <ApartmentOutlined />
                <Title level={5} className="playbook-designer__card-title">
                  Step Editor
                </Title>
                {selectedStepName ? <Tag color="blue">{selectedStepName}</Tag> : null}
              </Space>
              <Space>
                <Button
                  size="small"
                  disabled={!selectedPlaybookRef || !!parseError}
                  onClick={() => handleDrillDownReference(selectedPlaybookRef)}
                >
                  Drill Down
                </Button>
                <Button size="small" onClick={() => setStepEditorVisible((prev) => !prev)}>
                  {stepEditorVisible ? "Hide" : "Show"}
                </Button>
              </Space>
            </div>

            {!stepEditorVisible ? (
              <Alert
                type="info"
                showIcon
                message="Step editor is hidden. Select a step and click Show."
              />
            ) : (
              <>
                {renderStepEditorContent("drawer")}
                <div className="playbook-designer__step-sticky-bar">
                  <div className="playbook-designer__drawer-dirty">
                    <Tag color={stepAnyDirty ? "gold" : "default"}>
                      Step {stepAnyDirty ? "edited" : "clean"}
                    </Tag>
                    <Tag color={pipelineAnyDirty ? "gold" : "default"}>
                      Pipeline {pipelineAnyDirty ? "edited" : "clean"}
                    </Tag>
                    <Tag color={arcsDirty ? "gold" : "default"}>
                      Arcs {arcsDirty ? "edited" : "clean"}
                    </Tag>
                  </div>
                  {drawerActiveTab === "basics" || drawerActiveTab === "raw" ? (
                    stepDraftError ? <Alert type="error" showIcon message={stepDraftError} /> : null
                  ) : null}
                  {drawerActiveTab === "tasks" || drawerActiveTab === "policy" ? (
                    pipelineDraftError ? <Alert type="error" showIcon message={pipelineDraftError} /> : null
                  ) : null}
                  <Space className="playbook-designer__drawer-actions">
                    <Button onClick={() => setStepEditorVisible(false)}>Hide</Button>
                    <Button icon={<SaveOutlined />} onClick={applyPipelineDraft} disabled={!pipelineAnyDirty}>
                      Apply Pipeline
                    </Button>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      onClick={applyStepDraft}
                      disabled={!stepAnyDirty}
                    >
                      Apply Step
                    </Button>
                  </Space>
                </div>
              </>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};

export default PlaybookDesigner;
