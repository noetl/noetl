package main

import (
	"fmt"
	"time"

	"github.com/go-kit/kit/metrics"
)

type instrumentingMiddleware struct {
	requestCount   metrics.Counter
	requestLatency metrics.Histogram
	countResult    metrics.Histogram
	next           IFlow
}

func (mw instrumentingMiddleware) FlowPut(putRequest flowPutRequest) (output bool, err error) {
	defer func(begin time.Time) {
		lvs := []string{"method", "FlowPut", "error", fmt.Sprint(err != nil)}
		mw.requestCount.With(lvs...).Add(1)
		mw.requestLatency.With(lvs...).Observe(time.Since(begin).Seconds())
		if output {
			mw.countResult.Observe(1)
		} else {
			mw.countResult.Observe(0)
		}

	}(time.Now())

	output, err = mw.next.FlowPut(putRequest)
	return
}
