package flow

import (
	"context"
	"strings"
	"time"

	"github.com/coreos/etcd/clientv3"
	"github.com/pkg/errors"
)

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
	if conf.Id == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.Id, "/templates/") {
		return false, errors.New("id should start with '/template/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Delete(ctx, conf.Id)
	if err != nil {
		return false, errors.Wrap(err, "can not delete id ["+conf.Id+"]")
	}
	if gr.Deleted == 0 {
		return false, errors.New("no config with id [" + conf.Id + "]")
	}
	return true, nil
}

func (f *service) FlowPost(conf flowPostRequest) (bool, error) {
	if conf.Id == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.Id, "/") {
		return false, errors.New("id should start with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, conf.Id)
	if err != nil {
		return false, errors.Wrap(err, "can not create id ["+conf.Id+"]")
	}
	if len(gr.Kvs) == 0 {
		_, err := f.etcdClientAPI.Put(ctx, conf.Id, conf.Config)
		if err != nil {
			return false, errors.Wrap(err, "can not create id ["+conf.Id+"]")
		}
		return true, nil
	}
	return false, errors.New("config with id [" + conf.Id + "] already exist")
}

func (f *service) FlowPut(conf flowPutRequest) (bool, error) {
	if conf.Id == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.Id, "/") {
		return false, errors.New("id should start with '/'")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	gr, err := f.etcdClientAPI.Get(ctx, conf.Id)
	if err != nil {
		return false, errors.Wrap(err, "can not update id ["+conf.Id+"]")
	}
	if len(gr.Kvs) == 0 {
		return false, errors.New("id [" + conf.Id + "] not found")
	}
	_, err = f.etcdClientAPI.Put(ctx, conf.Id, conf.Config)
	if err != nil {
		return false, errors.Wrap(err, "can not update id ["+conf.Id+"]")
	}
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
