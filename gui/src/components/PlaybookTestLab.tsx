import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Input,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  FolderOpenOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RocketOutlined,
  SaveOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { PlaybookData } from "../types";
// @ts-ignore
import yaml from "js-yaml";

const { Text, Title } = Typography;

interface PlaybookTestLabProps {
  yamlContent: string;
  playbook: PlaybookData | null;
}

interface PlaybookTestCase {
  id: string;
  name: string;
  payloadText: string;
  assertionsText: string;
  running?: boolean;
  lastRun?: {
    passed: boolean;
    executionId?: string;
    status?: string;
    durationMs?: number;
    message?: string;
    details?: string[];
    ranAt?: string;
  };
}

const DEFAULT_ASSERTIONS = `assert(execution.status === "COMPLETED", "execution status should be COMPLETED");
assert(!execution.error, "execution should not return an error");
`;

function createDefaultTest(name = "Happy Path"): PlaybookTestCase {
  return {
    id: `test_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    name,
    payloadText: "{}",
    assertionsText: DEFAULT_ASSERTIONS,
  };
}

function normalizeStatus(status: string | undefined): string {
  return String(status || "").toUpperCase();
}

function isTerminalStatus(status: string | undefined): boolean {
  const s = normalizeStatus(status);
  return (
    s === "COMPLETED" ||
    s === "FAILED" ||
    s === "CANCELED" ||
    s === "CANCELLED" ||
    s === "ERROR"
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeIncomingTests(input: any): PlaybookTestCase[] {
  if (!Array.isArray(input)) return [createDefaultTest()];
  const tests = input
    .filter((entry) => entry && typeof entry === "object")
    .map((entry: any, idx: number) => ({
      id: String(entry.id || `test_${idx + 1}_${Date.now()}`),
      name: String(entry.name || `Test ${idx + 1}`),
      payloadText:
        typeof entry.payloadText === "string"
          ? entry.payloadText
          : JSON.stringify(entry.payload || {}, null, 2),
      assertionsText:
        typeof entry.assertionsText === "string"
          ? entry.assertionsText
          : typeof entry.assertions === "string"
            ? entry.assertions
            : DEFAULT_ASSERTIONS,
      running: false,
      lastRun: entry.lastRun,
    }));
  return tests.length > 0 ? tests : [createDefaultTest()];
}

const PlaybookTestLab: React.FC<PlaybookTestLabProps> = ({ yamlContent, playbook }) => {
  const [messageApi, messageContext] = message.useMessage();
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const [tests, setTests] = useState<PlaybookTestCase[]>([createDefaultTest()]);
  const [runningAll, setRunningAll] = useState(false);
  const [suiteId, setSuiteId] = useState("");
  const [suiteLoading, setSuiteLoading] = useState(false);
  const [suiteSaving, setSuiteSaving] = useState(false);
  const [suiteFilePath, setSuiteFilePath] = useState<string | null>(null);
  const [suiteUpdatedAt, setSuiteUpdatedAt] = useState<string | null>(null);
  const [suiteError, setSuiteError] = useState<string | null>(null);

  const parsedMetadata = useMemo(() => {
    try {
      const loaded = (yaml.load(yamlContent) || {}) as any;
      return {
        path: loaded?.metadata?.path || playbook?.path || "",
        version: String(loaded?.metadata?.version || playbook?.version || "latest"),
        parseError: null as string | null,
      };
    } catch (error: any) {
      return {
        path: playbook?.path || "",
        version: String(playbook?.version || "latest"),
        parseError: error?.message || "Failed to parse YAML",
      };
    }
  }, [yamlContent, playbook?.path, playbook?.version]);

  useEffect(() => {
    const nextSuite = parsedMetadata.path || playbook?.path || "";
    setSuiteId(nextSuite);
  }, [parsedMetadata.path, playbook?.path]);

  const loadSuiteFromRepo = async (targetSuiteId?: string) => {
    const effectiveSuiteId = (targetSuiteId || suiteId || "").trim();
    if (!effectiveSuiteId) {
      setTests([createDefaultTest()]);
      setSuiteFilePath(null);
      setSuiteUpdatedAt(null);
      return;
    }

    setSuiteLoading(true);
    setSuiteError(null);
    try {
      const response = await apiService.getPlaybookTestSuite(effectiveSuiteId);
      const loadedTests = normalizeIncomingTests(response.tests);
      setTests(loadedTests);
      setSuiteFilePath(response.file_path || null);
      setSuiteUpdatedAt(response.updated_at || null);
      messageApi.success(`Loaded suite from ${response.file_path}`);
    } catch (error: any) {
      if (error?.response?.status === 404) {
        setTests([createDefaultTest()]);
        setSuiteFilePath(null);
        setSuiteUpdatedAt(null);
        messageApi.warning("No suite file found in repo. Created an empty test suite in UI.");
      } else {
        const detail = error?.response?.data?.detail || error?.message || "Failed to load suite";
        setSuiteError(detail);
      }
    } finally {
      setSuiteLoading(false);
    }
  };

  useEffect(() => {
    if (suiteId.trim()) {
      loadSuiteFromRepo(suiteId.trim());
    } else {
      setTests([createDefaultTest()]);
      setSuiteFilePath(null);
      setSuiteUpdatedAt(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suiteId]);

  const saveSuiteToRepo = async () => {
    const effectiveSuiteId = suiteId.trim();
    if (!effectiveSuiteId) {
      messageApi.error("Suite id is required");
      return;
    }
    setSuiteSaving(true);
    setSuiteError(null);
    try {
      const payload = {
        playbook_path: parsedMetadata.path || effectiveSuiteId,
        tests,
        metadata: {
          saved_by: "gui",
          source: "PlaybookTestLab",
        },
      };
      const response = await apiService.savePlaybookTestSuite(effectiveSuiteId, payload);
      setSuiteFilePath(response.file_path || null);
      setSuiteUpdatedAt(response.updated_at || null);
      messageApi.success(`Suite saved to ${response.file_path}`);
    } catch (error: any) {
      setSuiteError(error?.response?.data?.detail || error?.message || "Failed to save suite");
    } finally {
      setSuiteSaving(false);
    }
  };

  const deleteSuiteFromRepo = async () => {
    const effectiveSuiteId = suiteId.trim();
    if (!effectiveSuiteId) return;
    setSuiteSaving(true);
    setSuiteError(null);
    try {
      const response = await apiService.deletePlaybookTestSuite(effectiveSuiteId);
      messageApi.success(`Deleted suite file ${response.file_path}`);
      setSuiteFilePath(null);
      setSuiteUpdatedAt(null);
      setTests([createDefaultTest()]);
    } catch (error: any) {
      setSuiteError(error?.response?.data?.detail || error?.message || "Failed to delete suite");
    } finally {
      setSuiteSaving(false);
    }
  };

  const exportSuiteJson = () => {
    const payload = {
      suite_id: suiteId || parsedMetadata.path || "playbook_suite",
      playbook_path: parsedMetadata.path || playbook?.path || "",
      tests,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const safeName = (suiteId || parsedMetadata.path || "playbook_suite").replace(/[^\w.-]+/g, "_");
    anchor.href = url;
    anchor.download = `${safeName}.testsuite.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importSuiteJson = async (file: File) => {
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const importedTests = normalizeIncomingTests(Array.isArray(parsed) ? parsed : parsed.tests);
      setTests(importedTests);
      if (parsed?.suite_id && typeof parsed.suite_id === "string") {
        setSuiteId(parsed.suite_id);
      }
      messageApi.success("Imported suite JSON into editor. Save to repo to persist.");
    } catch (error: any) {
      messageApi.error(error?.message || "Invalid suite JSON file");
    }
  };

  const updateTest = (testId: string, patch: Partial<PlaybookTestCase>) => {
    setTests((prev) => prev.map((test) => (test.id === testId ? { ...test, ...patch } : test)));
  };

  const addTest = () => {
    const newTest = createDefaultTest(`Test ${tests.length + 1}`);
    setTests((prev) => [...prev, newTest]);
  };

  const removeTest = (testId: string) => {
    setTests((prev) => prev.filter((test) => test.id !== testId));
  };

  const evaluateAssertions = (
    assertionsText: string,
    execution: any
  ): { passed: boolean; details: string[]; message?: string } => {
    const details: string[] = [];

    const assert = (condition: unknown, label = "assertion"): void => {
      if (!condition) {
        throw new Error(label);
      }
      details.push(`PASS: ${label}`);
    };

    const equals = (actual: unknown, expected: unknown, label?: string): void => {
      const pass = actual === expected;
      const defaultLabel = `expected ${JSON.stringify(actual)} to equal ${JSON.stringify(expected)}`;
      assert(pass, label || defaultLabel);
    };

    const contains = (container: unknown, value: unknown, label?: string): void => {
      let pass = false;
      if (typeof container === "string") pass = container.includes(String(value));
      if (Array.isArray(container)) pass = container.includes(value);
      if (
        container &&
        typeof container === "object" &&
        (typeof value === "string" || typeof value === "number" || typeof value === "symbol")
      ) {
        pass = value in (container as Record<string | number | symbol, unknown>);
      }
      const defaultLabel = `expected container to include ${JSON.stringify(value)}`;
      assert(pass, label || defaultLabel);
    };

    try {
      const assertionScript = assertionsText.trim() || DEFAULT_ASSERTIONS;
      const fn = new Function(
        "execution",
        "result",
        "events",
        "assert",
        "equals",
        "contains",
        assertionScript
      );
      fn(execution, execution?.result, execution?.events || [], assert, equals, contains);
      if (details.length === 0) {
        details.push("PASS: assertions executed");
      }
      return { passed: true, details };
    } catch (error: any) {
      return {
        passed: false,
        details,
        message: error?.message || "Assertion script failed",
      };
    }
  };

  const runSingleTest = async (testId: string): Promise<void> => {
    const test = tests.find((item) => item.id === testId);
    if (!test) return;

    if (!parsedMetadata.path) {
      updateTest(testId, {
        lastRun: {
          passed: false,
          message: "metadata.path is required in playbook YAML before running tests",
          ranAt: new Date().toISOString(),
        },
      });
      return;
    }

    let payload: any = {};
    try {
      payload = test.payloadText.trim() ? JSON.parse(test.payloadText) : {};
    } catch (error: any) {
      updateTest(testId, {
        lastRun: {
          passed: false,
          message: `Invalid payload JSON: ${error?.message || "Unknown error"}`,
          ranAt: new Date().toISOString(),
        },
      });
      return;
    }

    updateTest(testId, { running: true });
    const startedAt = Date.now();
    try {
      const executionStart = await apiService.executePlaybookWithPayload({
        path: parsedMetadata.path,
        version: parsedMetadata.version || "latest",
        payload,
      });
      const executionId = executionStart.execution_id;
      let execution = await apiService.getExecution(executionId);

      const maxPollCount = 120;
      let pollCount = 0;
      while (!isTerminalStatus(execution?.status) && pollCount < maxPollCount) {
        pollCount += 1;
        await sleep(1500);
        execution = await apiService.getExecution(executionId);
      }

      if (!isTerminalStatus(execution?.status)) {
        updateTest(testId, {
          running: false,
          lastRun: {
            passed: false,
            executionId,
            status: execution?.status,
            durationMs: Date.now() - startedAt,
            message: "Execution polling timed out before reaching terminal state",
            ranAt: new Date().toISOString(),
          },
        });
        return;
      }

      const assertionResult = evaluateAssertions(test.assertionsText, execution);
      updateTest(testId, {
        running: false,
        lastRun: {
          passed: assertionResult.passed,
          executionId,
          status: execution?.status,
          durationMs: Date.now() - startedAt,
          message: assertionResult.message,
          details: assertionResult.details,
          ranAt: new Date().toISOString(),
        },
      });
    } catch (error: any) {
      updateTest(testId, {
        running: false,
        lastRun: {
          passed: false,
          durationMs: Date.now() - startedAt,
          message: error?.message || "Execution failed",
          ranAt: new Date().toISOString(),
        },
      });
    }
  };

  const runAllTests = async () => {
    if (runningAll) return;
    setRunningAll(true);
    try {
      for (const test of tests) {
        // eslint-disable-next-line no-await-in-loop
        await runSingleTest(test.id);
      }
      messageApi.success("Finished running all tests");
    } finally {
      setRunningAll(false);
    }
  };

  const passedCount = tests.filter((test) => test.lastRun?.passed).length;
  const failedCount = tests.filter((test) => test.lastRun && !test.lastRun.passed).length;

  return (
    <div>
      {messageContext}

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Title level={5} style={{ margin: 0 }}>
            Workflow Test Lab
          </Title>
          <Text type="secondary">
            Run payload-based end-to-end tests and store suite files in repository-backed JSON.
          </Text>
          <Space wrap>
            <Tag color="blue">path: {parsedMetadata.path || "missing metadata.path"}</Tag>
            <Tag color="purple">version: {parsedMetadata.version || "latest"}</Tag>
            <Tag color="green">passed: {passedCount}</Tag>
            <Tag color="red">failed: {failedCount}</Tag>
          </Space>
          {parsedMetadata.parseError && (
            <Alert
              type="warning"
              showIcon
              message="YAML parse issue"
              description={parsedMetadata.parseError}
            />
          )}
          {!parsedMetadata.path && (
            <Alert
              type="error"
              showIcon
              message="Cannot run tests"
              description="Set metadata.path in YAML or save the playbook first."
            />
          )}
          {suiteError && <Alert type="error" showIcon message={suiteError} />}
          <Row gutter={8}>
            <Col span={16}>
              <Text type="secondary">Suite ID (repo file key)</Text>
              <Input
                value={suiteId}
                onChange={(e) => setSuiteId(e.target.value)}
                placeholder="examples/new_playbook"
              />
            </Col>
            <Col span={8}>
              <Text type="secondary">Repository file</Text>
              <Input value={suiteFilePath || "not saved"} readOnly />
            </Col>
          </Row>
          <Space wrap>
            <Button icon={<PlusOutlined />} onClick={addTest}>
              Add Test
            </Button>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              loading={runningAll}
              onClick={runAllTests}
              disabled={!parsedMetadata.path || tests.length === 0}
            >
              Run All
            </Button>
            <Button icon={<FolderOpenOutlined />} loading={suiteLoading} onClick={() => loadSuiteFromRepo()}>
              Load Suite File
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={suiteSaving}
              onClick={saveSuiteToRepo}
              disabled={!suiteId.trim()}
            >
              Save Suite File
            </Button>
            <Button danger icon={<DeleteOutlined />} loading={suiteSaving} onClick={deleteSuiteFromRepo}>
              Delete Suite File
            </Button>
            <Button
              icon={<UploadOutlined />}
              onClick={() => {
                importInputRef.current?.click();
              }}
            >
              Import JSON
            </Button>
            <Button icon={<DownloadOutlined />} onClick={exportSuiteJson}>
              Export JSON
            </Button>
          </Space>
          {suiteLoading && (
            <Space>
              <Spin size="small" />
              <Text type="secondary">Loading suite file from repo...</Text>
            </Space>
          )}
          {suiteUpdatedAt && (
            <Text type="secondary">Suite updated at: {new Date(suiteUpdatedAt).toLocaleString()}</Text>
          )}
        </Space>
      </Card>

      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) {
            importSuiteJson(file);
          }
          event.target.value = "";
        }}
      />

      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {tests.map((test) => (
          <Card
            key={test.id}
            size="small"
            title={
              <Space>
                <Input
                  value={test.name}
                  onChange={(e) => updateTest(test.id, { name: e.target.value })}
                  placeholder="Test name"
                  style={{ minWidth: 280 }}
                />
                {test.running ? <Spin size="small" /> : null}
                {test.lastRun && (
                  <Tag color={test.lastRun.passed ? "green" : "red"}>
                    {test.lastRun.passed ? "PASS" : "FAIL"}
                  </Tag>
                )}
              </Space>
            }
            extra={
              <Space>
                <Button
                  icon={<PlayCircleOutlined />}
                  loading={!!test.running}
                  onClick={() => runSingleTest(test.id)}
                  disabled={!parsedMetadata.path}
                >
                  Run
                </Button>
                <Button danger icon={<DeleteOutlined />} onClick={() => removeTest(test.id)}>
                  Delete
                </Button>
              </Space>
            }
          >
            <Row gutter={12}>
              <Col span={12}>
                <Text type="secondary">Payload JSON</Text>
                <Input.TextArea
                  rows={10}
                  value={test.payloadText}
                  onChange={(e) => updateTest(test.id, { payloadText: e.target.value })}
                  placeholder='{"query":"I need flight options from SFO to JFK"}'
                  style={{ fontFamily: "monospace", marginTop: 4 }}
                />
              </Col>
              <Col span={12}>
                <Text type="secondary">Assertions Script</Text>
                <Input.TextArea
                  rows={10}
                  value={test.assertionsText}
                  onChange={(e) => updateTest(test.id, { assertionsText: e.target.value })}
                  placeholder={DEFAULT_ASSERTIONS}
                  style={{ fontFamily: "monospace", marginTop: 4 }}
                />
              </Col>
            </Row>

            {test.lastRun && (
              <>
                <Divider />
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Space wrap>
                    {test.lastRun.executionId && (
                      <Tag color="blue">execution: {test.lastRun.executionId}</Tag>
                    )}
                    {test.lastRun.status && <Tag color="default">status: {test.lastRun.status}</Tag>}
                    {typeof test.lastRun.durationMs === "number" && (
                      <Tag color="default">duration: {test.lastRun.durationMs}ms</Tag>
                    )}
                    {test.lastRun.ranAt && (
                      <Tag color="default">{new Date(test.lastRun.ranAt).toLocaleString()}</Tag>
                    )}
                  </Space>
                  {test.lastRun.message && (
                    <Alert
                      type={test.lastRun.passed ? "success" : "error"}
                      showIcon
                      message={test.lastRun.message}
                    />
                  )}
                  {test.lastRun.details && test.lastRun.details.length > 0 && (
                    <Card size="small" bodyStyle={{ padding: 10 }}>
                      {test.lastRun.details.map((line, index) => (
                        <div key={`${test.id}-detail-${index}`}>
                          <Text>{line}</Text>
                        </div>
                      ))}
                    </Card>
                  )}
                </Space>
              </>
            )}
          </Card>
        ))}
      </Space>
    </div>
  );
};

export default PlaybookTestLab;
