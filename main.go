package main

import (
	"flag"
	"fmt"
	"net/http"
	"noetl/flow"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/coreos/etcd/clientv3"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/go-kit/kit/log"
)

func main() {
	logger := log.NewLogfmtLogger(os.Stdout)

	etcd, err := clientv3.New(clientv3.Config{
		DialTimeout: 5 * time.Second,
		Endpoints:   []string{"etcd:2379"},
	})
	if err != nil {
		logger.Log("failed to create etcd client", err)
		os.Exit(1)
	}
	defer etcd.Close()
	etcdAPI := clientv3.NewKV(etcd)

	var (
		addr     = envString("PORT", "8888")
		httpAddr = flag.String("http.addr", ":"+addr, "HTTP listen address")
	)

	httpLogger := log.With(logger, "component", "http")

	var flowService flow.Service
	flowService = flow.NewService(etcdAPI)
	flowService = flow.NewLoggingService(log.With(logger, "component", "flow"), flowService)
	flowService = flow.NewInstrumentingService(flowService)

	mux := http.NewServeMux()
	mux.Handle("/flow/", flow.MakeHandler(flowService, httpLogger)) //todo add version support from header request

	http.Handle("/", accessControl(mux))
	http.Handle("/metrics", promhttp.Handler())

	errs := make(chan error, 2)
	go func() {
		logger.Log("transport", "http", "address", *httpAddr, "msg", "listening")
		errs <- http.ListenAndServe(*httpAddr, nil)
	}()
	go func() {
		c := make(chan os.Signal)
		signal.Notify(c, syscall.SIGINT)
		errs <- fmt.Errorf("%s", <-c)
	}()

	logger.Log("terminated", <-errs)
}

func accessControl(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Origin, Content-Type")

		if r.Method == "OPTIONS" {
			return
		}

		h.ServeHTTP(w, r)
	})
}

func envString(env, fallback string) string {
	e := os.Getenv(env)
	if e == "" {
		return fallback
	}
	return e
}
