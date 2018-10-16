package service

import (
	"context"
	"log"
)

// FlowService describes the service.
type FlowService interface {
	Config(ctx context.Context, s string) (rs string, err error)
}

type basicFlowService struct{}

func (b *basicFlowService) Config(ctx context.Context, s string) (rs string, err error) {
	// TODO implement the business logic of Config
	log.Printf("%+v", s)
	rs = s
	return rs, err
}

// NewBasicFlowService returns a naive, stateless implementation of FlowService.
func NewBasicFlowService() FlowService {
	return &basicFlowService{}
}

// New returns a FlowService with all of the expected middleware wired in.
func New(middleware []Middleware) FlowService {
	var svc FlowService = NewBasicFlowService()
	for _, m := range middleware {
		svc = m(svc)
	}
	return svc
}
