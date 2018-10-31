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

func (mw *loggingService) FlowsDirectoryDelete(request flowsDirectoryDeleteRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowsDirectoryDelete",
			"input.Path", request.Path,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowsDirectoryDelete(request)
}

func (mw *loggingService) FlowDelete(request flowDeleteRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowDelete",
			"input.id", request.Id,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowDelete(request)
}

func (mw *loggingService) FlowPost(request flowPostRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowPost",
			"input.id", request.Id,
			"input.config", request.Config,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowPost(request)
}

func (mw *loggingService) FlowPut(request flowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowPut",
			"input.id", request.Id,
			"input.config", request.Config,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowPut(request)
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
