package workflows

// Workflow describes plan of execution.
type Workflow struct {
	Version     string          `json:"version"`
	ID          string          `json:"id"`
	Description string          `json:"description"`
	Context     Context         `json:"context"`
	Tasks       map[string]Task `json:"tasks"`
}

// Context of the execution
type Context struct {
	Aws Aws `json:"aws"`
}

// Aws credentials
type Aws struct {
	AccessKey string `json:"access-key"`
	SecretKey string `json:"secret-key"`
}

// Task is a sequence of steps to execute
type Task struct {
	Description string                   `json:"description"`
	Steps       []map[string]interface{} `json:"steps"`
	Loop        []string                 `json:"loop"`
	Status      bool                     `json:"status"`
	Require     []string                 `json:"require"`
}

// S3 module structure
type S3 struct {
	Action   string `json:"action"`
	Path     string `json:"path"`
	Validate string `json:"validate"`
	Context  string `json:"context"`
}
