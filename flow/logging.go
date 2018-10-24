package main

import (
	"time"

	"github.com/go-kit/kit/log"
)

type loggingMiddleware struct {
	logger log.Logger
	next   IFlow
}

func (mw loggingMiddleware) FlowPut(putRequest flowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.logger.Log(
			"method", "FlowPut",
			"input", putRequest,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())

	output, err = mw.next.FlowPut(putRequest) // тут мы вызовим следующюю миделвару или уже бизнеслогику сервиса
	return
}
