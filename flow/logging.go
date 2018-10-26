package flow

import (
	"time"

	"github.com/go-kit/kit/log"
)

type loggingService struct {
	logger log.Logger
	Service Service
}

// NewLoggingService returns a new instance of a logging Service.
func NewLoggingService(logger log.Logger, s Service) Service {
	return &loggingService{logger, s}
}

func (mw *loggingService) FlowPut(putRequest flowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowPut",
			"input.id", putRequest.Id,
			"input.config", putRequest.Config,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowPut(putRequest)
}

func (mw *loggingService) FlowGet(id string) (config string, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowGet",
			"configId", id,
			"config", config,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return  mw.Service.FlowGet(id)
}
