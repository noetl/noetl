package model

// Workflow is a main
type Workflow struct {
	ID          string  `json:"id"`
	Description string  `json:"description"`
	Context     Context `json:"context"`
}

// Context is ..
type Context struct {
	Aws Aws `json:"aws"`
}

// Aws is .
type Aws struct {
	AccessKey string `json:"access-key"`
	SecretKey string `json:"secret-key"`
}
