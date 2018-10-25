package flow

import (
	"fmt"
	"time"

	"github.com/go-kit/kit/metrics"
)

type InstrumentingMiddleware struct {
	RequestCount   metrics.Counter
	RequestLatency metrics.Histogram
	CountResult    metrics.Histogram
	Next           IFlow
}

func (mw InstrumentingMiddleware) FlowPut(putRequest FlowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		lvs := []string{"method", "FlowPut", "error", fmt.Sprint(err != nil)}
		mw.RequestCount.With(lvs...).Add(1)
		mw.RequestLatency.With(lvs...).Observe(time.Since(begin).Seconds())
		if output {
			mw.CountResult.Observe(1)
		} else {
			mw.CountResult.Observe(0)
		}

	}(time.Now())

	output, err = mw.Next.FlowPut(putRequest)
	return
}
