package flow

import (
	"noetl/workflows"
	"time"

	"github.com/go-kit/kit/log"
)

type loggingService struct {
	logger  log.Logger
	Service Service
}

// NewLoggingService returns a new instance of a logging Service.
func NewLoggingService(logger log.Logger, s Service) Service {
	return &loggingService{logger, s}
}

func (mw *loggingService) FlowRun(workflow workflows.Workflow) (err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
			"method", "FlowRun",
			//"output", treeState,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowRun(workflow)
}

func (mw *loggingService) FlowDirectoryTreeGet() (treeState string, err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
			"method", "FlowDirectoryTreeGet",
			"output", treeState,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowDirectoryTreeGet()
}

func (mw *loggingService) FlowDirectoryTreeSave(treeState string) (err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
			"method", "FlowDirectoryTreeSave",
			"input", treeState,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowDirectoryTreeSave(treeState)
}

func (mw *loggingService) FlowsDirectoryDelete(request flowsDirectoryDeleteRequest) (output bool, err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
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
		mw.logger.Log(
			"method", "FlowDelete",
			"input.id", request.ID,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowDelete(request)
}

func (mw *loggingService) FlowPost(request flowPostRequest) (output bool, err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
			"method", "FlowPost",
			"input.id", request.ID,
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
		mw.logger.Log(
			"method", "FlowPut",
			"input.id", request.ID,
			"input.workflow", request.Workflow,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowPut(request)
}

func (mw *loggingService) FlowGet(id string) (config string, err error) {
	defer func(begin time.Time) {
		mw.logger.Log(
			"method", "FlowGet",
			"configId", id,
			"config", config,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())
	return mw.Service.FlowGet(id)
}
