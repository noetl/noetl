package flow

import (
	"context"
	"encoding/json"
	"noetl/workflows"
	"strings"
	"time"

	"github.com/golang/glog"

	"github.com/coreos/etcd/clientv3"
	"github.com/pkg/errors"
)

// Service describes flow interface.
type Service interface {
	//save state directory tree for navigation about templates
	FlowDirectoryTreeSave(string) error

	//get state directory tree for navigation about templates
	FlowDirectoryTreeGet() (string, error)

	// Remove all flow configs when is directory path "/templates/.../.../"
	FlowsDirectoryDelete(flowsDirectoryDeleteRequest) (bool, error)

	// Remove flow config
	FlowDelete(flowDeleteRequest) (bool, error)

	// add new flow config
	FlowPost(flowPostRequest) (bool, error)

	// update flow config
	FlowPut(flowPutRequest) (bool, error)

	//get flow config
	FlowGet(id string) (string, error)

	//run flow config
	FlowRun(workflow workflows.Workflow) error
}

type service struct {
	etcdClientAPI clientv3.KV
}

// NewService returns flow service with all dependencies.
func NewService(etcdClientAPI clientv3.KV) Service {
	return &service{etcdClientAPI}
}

func (f *service) FlowDirectoryTreeSave(treeState string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, err := f.etcdClientAPI.Delete(ctx, "treeDirectoryState")
	if err != nil {
		return errors.Wrap(err, "can not save directory tree state")
	}

	_, err = f.etcdClientAPI.Put(ctx, "treeDirectoryState", treeState)
	if err != nil {
		return errors.Wrap(err, "can not save directory tree state")
	}
	return nil
}

func (f *service) FlowDirectoryTreeGet() (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, "treeDirectoryState")
	if err != nil {
		return "", errors.Wrap(err, "can not get directory tree state")
	}
	if len(gr.Kvs) == 0 {
		return "{\"name\": \"templates\",\"root\": true,\"isOpen\": true,\"children\": []}\n", nil
	}
	return string(gr.Kvs[0].Value), nil
}

func (f *service) FlowsDirectoryDelete(conf flowsDirectoryDeleteRequest) (bool, error) {
	if conf.Path == "" {
		return false, errors.New("path is required")
	}
	if !strings.HasPrefix(conf.Path, "/templates/") || !strings.HasSuffix(conf.Path, "/") {
		return false, errors.New("path should start with '/template/' and end with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Delete(ctx, conf.Path, clientv3.WithPrefix())
	if err != nil {
		return false, errors.Wrap(err, "can not delete directory ["+conf.Path+"]")
	}
	if gr.Deleted == 0 {
		return false, errors.New("no directory with path [" + conf.Path + "]")
	}
	return true, nil
}

func (f *service) FlowDelete(conf flowDeleteRequest) (bool, error) {
	if conf.ID == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.ID, "/templates/") {
		return false, errors.New("id should start with '/template/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Delete(ctx, conf.ID)
	if err != nil {
		return false, errors.Wrap(err, "can not delete id ["+conf.ID+"]")
	}
	if gr.Deleted == 0 {
		return false, errors.New("no config with id [" + conf.ID + "]")
	}
	return true, nil
}

func (f *service) FlowPost(conf flowPostRequest) (bool, error) {
	if conf.ID == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.ID, "/") {
		return false, errors.New("id should start with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, conf.ID)
	if err != nil {
		return false, errors.Wrap(err, "can not create id ["+conf.ID+"]")
	}
	if len(gr.Kvs) == 0 {
		_, err := f.etcdClientAPI.Put(ctx, conf.ID, conf.Config)
		if err != nil {
			return false, errors.Wrap(err, "can not create id ["+conf.ID+"]")
		}
		return true, nil
	}
	return false, errors.New("config with id [" + conf.ID + "] already exist")
}

func (f *service) FlowPut(conf flowPutRequest) (bool, error) {
	if conf.ID == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.ID, "/") {
		return false, errors.New("id should start with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, conf.ID)
	if err != nil {
		return false, errors.Wrap(err, "can not update id ["+conf.ID+"]")
	}
	if len(gr.Kvs) == 0 {
		glog.V(4).Infoln("id [" + conf.ID + "] not found")
		// return false, errors.New("id [" + conf.ID + "] not found")
	}
	b, err := json.Marshal(conf.Workflow)
	if err != nil {
		glog.Fatalln(err)
	}
	_, err = f.etcdClientAPI.Put(ctx, conf.ID, string(b))
	if err != nil {
		return false, errors.Wrap(err, "can not update id ["+conf.ID+"]")
	}
	reconcile(conf.Workflow)
	return true, nil
}

func (f *service) FlowGet(id string) (string, error) {
	if id == "" {
		return "", errors.New("id is required")
	}
	if !strings.HasPrefix(id, "/") {
		return "", errors.New("id should start with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, id)
	if err != nil {
		return "", errors.Wrap(err, "can not get id ["+id+"]")
	}
	if len(gr.Kvs) == 0 {
		return "", errors.New("config with id [" + id + "] not found")
	}
	return string(gr.Kvs[0].Value), nil
}

func (f *service) FlowRun(workflow workflows.Workflow) error {
	reconcile(workflow)
	return nil
}

func reconcile(wf workflows.Workflow) {
	completed := 0
	for {
		for task, value := range wf.Tasks {
			if !value.Status && depsResolved(value, wf) {
				wf.Tasks[task] = processTask(task, value, wf.Context)
				completed++
			}
		}
		if len(wf.Tasks) == completed {
			break
		}
		glog.V(3).Infof("reconciling, workflow's id: %s", wf.ID)
		time.Sleep(2 * time.Second)
	}
}

func processTask(name string, t workflows.Task, ctx map[string]interface{}) workflows.Task {
	glog.V(3).Infof("processing task: %s", name)
	for _, steps := range t.Steps {
		processStep(steps, ctx)
	}
	t.Status = true
	return t
}

func depsResolved(t workflows.Task, wf workflows.Workflow) bool {
	glog.V(4).Infoln("cheking task dependencies")
	resolved := true
	for _, reqTask := range t.Require {
		if !wf.Tasks[reqTask].Status {
			resolved = false
		}
	}
	return resolved
}

func processStep(m map[string]interface{}, ctx map[string]interface{}) {
	var moduleCtx string
	var ctxObj map[string]interface{}
	if ctx, ok := m["context"].(string); ok {
		moduleCtx = ctx
	}
	if ctx, ok := ctx[moduleCtx].(map[string]interface{}); ok {
		ctxObj = ctx
	}
	for module, step := range m {
		switch module {
		case "s3":
			s3(step, ctxObj)
		case "rest":
			rest(step, ctxObj)
		case "aggregate":
			aggregate(step, ctxObj)
		}
	}
}
