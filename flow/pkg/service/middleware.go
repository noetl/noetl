package service

import (
	"context"
	log "github.com/go-kit/kit/log"
)

// Middleware describes a service middleware.
type Middleware func(FlowService) FlowService

type loggingMiddleware struct {
	logger log.Logger
	next   FlowService
}

// LoggingMiddleware takes a logger as a dependency
// and returns a FlowService Middleware.
func LoggingMiddleware(logger log.Logger) Middleware {
	return func(next FlowService) FlowService {
		return &loggingMiddleware{logger, next}
	}

}

func (l loggingMiddleware) Config(ctx context.Context, s string) (rs string, err error) {
	defer func() {
		l.logger.Log("method", "Config", "s", s, "rs", rs, "err", err)
	}()
	return l.next.Config(ctx, s)
}
