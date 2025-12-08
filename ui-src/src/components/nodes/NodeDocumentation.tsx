import { Modal, Tabs, Typography } from 'antd';
import { CodeEditor } from '../CodeEditor';

const { Title, Paragraph, Text } = Typography;
const { TabPane } = Tabs;

interface NodeDocumentationProps {
    open: boolean;
    onClose: () => void;
    nodeType: 'http' | 'python' | 'postgres' | 'duckdb' | 'playbooks' | 'workbook';
}

const HTTP_DOCS = {
    overview: `The HTTP node allows you to make REST API calls with support for all standard HTTP methods. It supports Jinja2 templating for dynamic values in endpoints, headers, params, and payload.`,
    parameters: [
        { name: 'Method', desc: 'HTTP method: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS' },
        { name: 'Endpoint', desc: 'API endpoint URL. Supports Jinja2 templating: {{ api }}/users/{{ user_id }}' },
        { name: 'Headers', desc: 'HTTP headers as JSON object. Example: {"Authorization": "Bearer {{ token }}"}' },
        { name: 'Params', desc: 'Query parameters as JSON object. Example: {"limit": 10, "offset": 0}' },
        { name: 'Payload', desc: 'Request body as JSON object (for POST/PUT/PATCH). Example: {"name": "{{ user_name }}"}' }
    ],
    example: `# Example HTTP Node Configuration
Method: POST
Endpoint: {{ api_base }}/v1/users
Headers: {
  "Authorization": "Bearer {{ secret.API_TOKEN }}",
  "Content-Type": "application/json"
}
Params: {
  "include": "profile,settings"
}
Payload: {
  "username": "{{ workload.username }}",
  "email": "{{ workload.email }}"
}`
};

const PYTHON_DOCS = {
    overview: `The Python node executes Python code with a main() function that receives input data and returns results. It supports both inline code and module references.`,
    parameters: [
        { name: 'Code', desc: 'Python code with a main() function. Input data is passed as parameter.' },
        { name: 'Module', desc: 'Alternative: Python module path (e.g., "scoring.calculator")' },
        { name: 'Callable', desc: 'Function name in the module to call (e.g., "compute_score")' }
    ],
    example: `# Example Python Code
def main(input_data):
    # Access input data
    user_rating = input_data.get("rating", 0)
    
    # Perform transformation
    score = user_rating * 10
    
    # Return result
    return {
        "score": score,
        "grade": "A" if score >= 90 else "B"
    }

# Or use module reference:
Module: scoring.calculator
Callable: compute_user_score`
};

const POSTGRES_DOCS = {
    overview: `The Postgres node executes SQL queries against PostgreSQL databases. It supports parameterized queries and credential management.`,
    parameters: [
        { name: 'Query', desc: 'SQL query to execute. Use %(param)s for parameterized queries.' },
        { name: 'Auth', desc: 'Credential reference for database connection (e.g., "pg_prod")' },
        { name: 'Params', desc: 'Query parameters as JSON object. Example: {"user_id": "{{ workload.user_id }}"}' }
    ],
    example: `# Example Postgres Query
Query:
SELECT id, name, email, created_at
FROM users
WHERE id = %(user_id)s
  AND status = %(status)s

Auth: pg_production

Params: {
  "user_id": "{{ workload.user_id }}",
  "status": "active"
}`
};

const DUCKDB_DOCS = {
    overview: `The DuckDB node executes analytical SQL queries using DuckDB, an in-memory analytical database. Excellent for data analytics and CSV/Parquet processing.`,
    parameters: [
        { name: 'Query', desc: 'DuckDB SQL query. Supports reading CSV, Parquet, JSON files directly.' },
        { name: 'File', desc: 'Optional: Path to DuckDB database file for persistence. Supports templating.' }
    ],
    example: `# Example DuckDB Query
Query:
SELECT 
  user_id,
  COUNT(*) as event_count,
  AVG(amount) as avg_amount
FROM read_csv('{{ workload.csv_path }}')
WHERE date >= '2024-01-01'
GROUP BY user_id
ORDER BY event_count DESC

File: {{ workload.db_path }}

# Reading Parquet files:
SELECT * FROM read_parquet('{{ s3_path }}/data.parquet')`
};

const PLAYBOOKS_DOCS = {
    overview: `The Playbooks node calls another playbook as a sub-workflow, enabling modular and reusable workflow composition.`,
    parameters: [
        { name: 'Catalog Path', desc: 'Path to the playbook in the catalog (e.g., "playbooks/user_scorer")' },
        { name: 'Entry Step', desc: 'Optional: Custom entry point step (defaults to "start")' },
        { name: 'Return Step', desc: 'Optional: Step to return to in parent playbook when sub-playbook completes' }
    ],
    example: `# Example Playbook Call
Catalog Path: playbooks/data_processor

Entry Step: validate_data

Return Step: aggregate_results

# The sub-playbook receives the current workload data
# and returns its results to the parent workflow.`
};

const WORKBOOK_DOCS = {
    overview: `The Workbook node references a reusable task defined in the playbook's workbook section. This promotes code reuse and modularity.`,
    parameters: [
        { name: 'Task Name', desc: 'Name of the task defined in the workbook section to execute' }
    ],
    example: `# Example Workbook Reference
Task Name: transform_user_data

# The workbook section must define this task:
workbook:
  - name: transform_user_data
    type: python
    code: |
      def main(data):
        return {"transformed": data}`
};


const DOCS_MAP = {
    http: HTTP_DOCS,
    python: PYTHON_DOCS,
    postgres: POSTGRES_DOCS,
    duckdb: DUCKDB_DOCS,
    playbooks: PLAYBOOKS_DOCS,
    workbook: WORKBOOK_DOCS,
};

export function NodeDocumentation({ open, onClose, nodeType }: NodeDocumentationProps) {
    const docs = DOCS_MAP[nodeType];
    const nodeTitle = nodeType.charAt(0).toUpperCase() + nodeType.slice(1);

    return (
        <Modal
            open={open}
            onCancel={onClose}
            title={`${nodeTitle} Node Documentation`}
            width={800}
            footer={null}
        >
            <Tabs defaultActiveKey="overview">
                <TabPane tab="Overview" key="overview">
                    <Typography>
                        <Paragraph>{docs.overview}</Paragraph>
                    </Typography>
                </TabPane>
                <TabPane tab="Parameters" key="parameters">
                    <Typography>
                        {docs.parameters.map((param, idx) => (
                            <div key={idx} style={{ marginBottom: 16 }}>
                                <Title level={5} style={{ marginBottom: 4 }}>
                                    {param.name}
                                </Title>
                                <Paragraph style={{ marginLeft: 16 }}>
                                    {param.desc}
                                </Paragraph>
                            </div>
                        ))}
                    </Typography>
                </TabPane>
                <TabPane tab="Example" key="example">
                    <CodeEditor
                        value={docs.example}
                        onChange={() => { }}
                        language={nodeType === 'python' ? 'python' : nodeType === 'postgres' || nodeType === 'duckdb' ? 'sql' : 'yaml'}
                        height={400}
                        readOnly
                    />
                </TabPane>
            </Tabs>
        </Modal>
    );
}
