package flow

import (
	"context"
	"errors"
	"github.com/coreos/etcd/clientv3"
	"time"
)

// Service это интерфейс нашего сервиса Flow
type Service interface {
	FlowPut(flowPutRequest) (bool, error)
	FlowGet(id string) (string, error)
}

// ErrInvalidArgument is returned when one or more arguments are invalid.
var ErrInvalidArgument = errors.New("invalid argument")

type service struct {
	etcdDataBaseClientApi clientv3.KV
}

func NewService(etcdDataBaseClientApi clientv3.KV) Service {
	return &service{etcdDataBaseClientApi}
}

func (f *service) FlowPut(conf flowPutRequest) (bool, error) {
	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	if conf.Id == "" {
		return false, errors.New("flow Id should not be empty")
	}
	f.etcdDataBaseClientApi.Put(ctxForEtcd, conf.Id, conf.Config)
	return true, nil
}

func (f *service) FlowGet(id string) (string, error) {
	ctxForEtcd, _ := context.WithTimeout(context.Background(), 10*time.Second)
	gr, err := f.etcdDataBaseClientApi.Get(ctxForEtcd, id)
	if err != nil {
		return "", err
	}
	if len(gr.Kvs)==0 {
		return "", errors.New("config id not found")
	}

	return string(gr.Kvs[0].Value), nil
}
