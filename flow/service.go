package flow

import (
	"context"
	"errors"
	"github.com/coreos/etcd/clientv3"
	"strings"
	"time"
)

// Service это интерфейс нашего сервиса Flow
type Service interface {
	FlowDelete(flowDeleteRequest) (bool, error)
	FlowPost(flowPostRequest) (bool, error)
	FlowPut(flowPutRequest) (bool, error)
	FlowGet(id string) (string, error)
}

type service struct {
	etcdClientApi clientv3.KV
}

func NewService(etcdClientApi clientv3.KV) Service {
	return &service{etcdClientApi}
}

func (f *service) FlowDelete(conf flowDeleteRequest) (bool, error) {

	if conf.Id == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.Id, "/templates/") {
		return false, errors.New("id should start with '/template/'")
	}
	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	gr, err := f.etcdClientApi.Delete(ctxForEtcd, conf.Id, clientv3.WithPrefix())
	if err != nil {
		return false, err
	}
	if gr.Deleted==0 {
		return false, errors.New("no configs with prefix id [" + conf.Id + "]")
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
	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	gr, err := f.etcdClientApi.Get(ctxForEtcd, conf.Id)
	if err != nil {
		return false, err
	}
	if len(gr.Kvs) == 0 {
		f.etcdClientApi.Put(ctxForEtcd, conf.Id, conf.Config)
		return true, nil
	} else {
		return false, errors.New("config with id [" + conf.Id + "] already exist")
	}
}

func (f *service) FlowPut(conf flowPutRequest) (bool, error) {

	if conf.Id == "" {
		return false, errors.New("id is required")
	}
	if !strings.HasPrefix(conf.Id, "/") {
		return false, errors.New("id should start with '/'")
	}
	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	gr, err := f.etcdClientApi.Get(ctxForEtcd, conf.Id)
	if err != nil {
		return false, err
	}
	if len(gr.Kvs) == 0 {
		return false, errors.New("id [" + conf.Id + "] not found")
	}
	f.etcdClientApi.Put(ctxForEtcd, conf.Id, conf.Config)
	return true, nil
}

func (f *service) FlowGet(id string) (string, error) {
	if id == "" {
		return "", errors.New("id is required")
	}
	if !strings.HasPrefix(id, "/") {
		return "", errors.New("id should start with '/'")
	}

	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	gr, err := f.etcdClientApi.Get(ctxForEtcd, id)
	if err != nil {
		return "", err
	}
	if len(gr.Kvs) == 0 {
		return "", errors.New("config with id [" + id + "] not found")
	}

	return string(gr.Kvs[0].Value), nil
}
