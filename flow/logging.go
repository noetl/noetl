package flow

import (
	"time"

	"github.com/go-kit/kit/log"
)

type LoggingMiddleware struct {
	Logger log.Logger
	Next   IFlow
}

func (mw LoggingMiddleware) FlowPut(putRequest FlowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		_ = mw.Logger.Log(
			"method", "FlowPut",
			"input", putRequest,
			"output", output,
			"err", err,
			"took", time.Since(begin),
		)
	}(time.Now())

	output, err = mw.Next.FlowPut(putRequest) // тут мы вызовим следующюю миделвару или уже бизнеслогику сервиса
	return
}
