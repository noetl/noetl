package flow

import (
	"fmt"
	"time"

	"github.com/go-kit/kit/metrics"
	kitprometheus "github.com/go-kit/kit/metrics/prometheus"
	stdprometheus "github.com/prometheus/client_golang/prometheus"
)

type instrumentingService struct {
	requestCount   metrics.Counter
	requestLatency metrics.Histogram
	countResult    metrics.Histogram
	Service        Service
}

// NewInstrumentingService returns an instance of an instrumenting Service.
func NewInstrumentingService(s Service) Service {
	return &instrumentingService{
		requestCount: kitprometheus.NewCounterFrom(stdprometheus.CounterOpts{
			Namespace: "api",
			Subsystem: "flow_service",
			Name:      "request_count",
			Help:      "Number of requests received.",
		}, []string{"method", "error"}),
		requestLatency: kitprometheus.NewSummaryFrom(stdprometheus.SummaryOpts{
			Namespace: "api",
			Subsystem: "flow_service",
			Name:      "request_latency_microseconds",
			Help:      "Total duration of requests in microseconds.",
		}, []string{"method", "error"}),
		countResult: kitprometheus.NewSummaryFrom(stdprometheus.SummaryOpts{
			Namespace: "api",
			Subsystem: "flow_service",
			Name:      "count_result",
			Help:      "The result of each count method.",
		}, []string{}),
		Service: s,
	}
}

func (mw *instrumentingService) FlowDelete(request flowDeleteRequest) (output bool, err error) {
	defer func(begin time.Time) {
		lvs := []string{"method", "FlowDelete", "error", fmt.Sprint(err != nil)}
		mw.requestCount.With(lvs...).Add(1)
		mw.requestLatency.With(lvs...).Observe(time.Since(begin).Seconds())
		if output {
			mw.countResult.Observe(1)
		} else {
			mw.countResult.Observe(0)
		}

	}(time.Now())
	return mw.Service.FlowDelete(request)
}

func (mw *instrumentingService) FlowPost(request flowPostRequest) (output bool, err error) {
	defer func(begin time.Time) {
		lvs := []string{"method", "FlowPost", "error", fmt.Sprint(err != nil)}
		mw.requestCount.With(lvs...).Add(1)
		mw.requestLatency.With(lvs...).Observe(time.Since(begin).Seconds())
		if output {
			mw.countResult.Observe(1)
		} else {
			mw.countResult.Observe(0)
		}

	}(time.Now())
	return mw.Service.FlowPost(request)
}

func (mw *instrumentingService) FlowPut(request flowPutRequest) (output bool, err error) {
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
	return mw.Service.FlowPut(request)
}

func (mw *instrumentingService) FlowGet(id string) (config string, err error) {
	defer func(begin time.Time) {
		lvs := []string{"method", "FlowPut", "error", fmt.Sprint(err != nil)}
		mw.requestCount.With(lvs...).Add(1)
		mw.requestLatency.With(lvs...).Observe(time.Since(begin).Seconds())
		if err != nil {
			mw.countResult.Observe(1)
		} else {
			mw.countResult.Observe(0)
		}

	}(time.Now())
	return mw.Service.FlowGet(id)
}
