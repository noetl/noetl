import React, { useState, useEffect } from 'react';
import { Layout, Button, Input, Typography, Space, Spin, Alert, Card, Row, Col, message } from 'antd';
import { SaveOutlined, PlayCircleOutlined, CheckCircleOutlined, FileTextOutlined } from '@ant-design/icons';
import { apiService } from '../services/api';
import { PlaybookData } from '../types';

const { Content } = Layout;
const { Title, Text } = Typography;
const { TextArea } = Input;

const Editor: React.FC = () => {
  const [playbook, setPlaybook] = useState<PlaybookData | null>(null);
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors?: string[] } | null>(null);

  // Get playbook ID from URL parameters
  const urlParams = new URLSearchParams(window.location.search);
  const playbookId = urlParams.get('id');

  useEffect(() => {
    if (playbookId) {
      loadPlaybook(playbookId);
    } else {
      // Create new playbook template
      setContent(`# New Playbook
name: "untitled-playbook"
description: "Enter description here"
tasks:
  - name: "sample-task"
    type: "log"
    config:
      message: "Hello from NoETL!"
`);
    }
  }, [playbookId]);

  const loadPlaybook = async (id: string) => {
    try {
      setLoading(true);
      setError(null);

      const [playbookData, playbookContent] = await Promise.all([
        apiService.getPlaybook(id),
        apiService.getPlaybookContent(id)
      ]);

      setPlaybook(playbookData);
      setContent(playbookContent);
    } catch (err: any) {
      console.error('Failed to load playbook:', err);
      // IMPROVEMENT: Display the specific error from the server
      const detail = err.response?.data?.detail || 'An unknown error occurred. Check the server logs.';
      const status = err.response?.status ? ` (Status: ${err.response.status})` : '';
      setError(`Failed to load playbook content: ${detail}${status}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!content.trim()) {
      message.error('Playbook content cannot be empty');
      return;
    }

    try {
      setSaving(true);

      if (playbookId) {
        // Update existing playbook
        await apiService.savePlaybookContent(playbookId, content);
        message.success('Playbook saved successfully');
      } else {
        // Create new playbook
        const newPlaybook = await apiService.createPlaybook({
          name: 'New Playbook',
          description: 'Created from editor',
          status: 'draft'
        });
        await apiService.savePlaybookContent(newPlaybook.id, content);
        setPlaybook(newPlaybook);
        window.history.pushState({}, '', `/editor?id=${newPlaybook.id}`);
        message.success('New playbook created and saved');
      }
    } catch (err) {
      console.error('Failed to save playbook:', err);
      message.error('Failed to save playbook');
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    try {
      setValidating(true);
      const result = await apiService.validatePlaybook(content);
      setValidationResult(result);

      if (result.valid) {
        message.success('Playbook is valid');
      } else {
        message.error('Playbook validation failed');
      }
    } catch (err) {
      console.error('Validation failed:', err);
      message.error('Validation failed');
    } finally {
      setValidating(false);
    }
  };

  const handleExecute = async () => {
    if (!playbook) {
      message.error('Please save the playbook first');
      return;
    }

    try {
      setExecuting(true);
      await apiService.executePlaybook(playbook.id);
      message.success('Playbook execution started');
      // Redirect to execution page
      window.location.href = '/execution';
    } catch (err) {
      console.error('Failed to execute playbook:', err);
      message.error('Failed to execute playbook');
    } finally {
      setExecuting(false);
    }
  };

  if (loading) {
    return (
      <Content style={{ padding: '50px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>Loading editor...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content style={{ padding: '50px' }}>
        <Alert message="Error" description={error} type="error" showIcon />
      </Content>
    );
  }

  return (
    <Content>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Title level={2}>
              <FileTextOutlined /> Playbook Editor
            </Title>
            {playbook && (
              <Text type="secondary">
                Editing: {playbook.name} (ID: {playbook.id})
              </Text>
            )}
          </Col>
          <Col>
            <Space>
              <Button
                type="default"
                icon={<CheckCircleOutlined />}
                loading={validating}
                onClick={handleValidate}
              >
                Validate
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={handleSave}
              >
                Save
              </Button>
              <Button
                type="default"
                icon={<PlayCircleOutlined />}
                loading={executing}
                onClick={handleExecute}
                disabled={!playbook}
              >
                Execute
              </Button>
            </Space>
          </Col>
        </Row>

        {/* Validation Results */}
        {validationResult && (
          <Card size="small">
            <Alert
              message={validationResult.valid ? 'Playbook is valid' : 'Validation failed'}
              description={
                validationResult.errors && validationResult.errors.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {validationResult.errors.map((error, index) => (
                      <li key={index}>{error}</li>
                    ))}
                  </ul>
                ) : undefined
              }
              type={validationResult.valid ? 'success' : 'error'}
              showIcon
            />
          </Card>
        )}

        {/* Editor */}
        <Card>
          <TextArea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter your playbook YAML content here..."
            autoSize={{ minRows: 20, maxRows: 30 }}
            style={{ fontFamily: 'monospace' }}
          />
        </Card>

        {/* Help text */}
        <Card size="small">
          <Text type="secondary">
            <strong>Tips:</strong> Use YAML format for playbook definition.
            Validate your playbook before saving to catch syntax errors.
          </Text>
        </Card>
      </Space>
    </Content>
  );
};

export default Editor;
