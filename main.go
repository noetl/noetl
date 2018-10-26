package main

import (
	"flag"
	"fmt"
	"github.com/coreos/etcd/clientv3"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"net/http"
	"noetl/flow"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-kit/kit/log"
)

func main() {
	logger := log.NewLogfmtLogger(os.Stderr)

	//init etcd db
	etcdDataBaseClient, err := clientv3.New(clientv3.Config{
		DialTimeout: 2 * time.Second,
		Endpoints:   []string{"127.0.0.1:2379"},
	})
	if err != nil {
		logger.Log("etcd", err)
	}
	defer etcdDataBaseClient.Close()

	etcdDataBaseClientApi := clientv3.NewKV(etcdDataBaseClient)

	var (
		addr     = envString("PORT", "8888")
		httpAddr = flag.String("http.addr", ":"+addr, "HTTP listen address")
	)

	httpLogger := log.With(logger, "component", "http")

	var flowService flow.Service
	flowService = flow.NewService(etcdDataBaseClientApi)
	flowService = flow.NewLoggingService(log.With(logger, "component", "flow"), flowService)
	flowService = flow.NewInstrumentingService(flowService)

	mux := http.NewServeMux()
	mux.Handle("/flow/v1/", flow.MakeHandler(flowService, httpLogger))

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
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

