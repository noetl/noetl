package main

import (
	"net/http"
	"os"

	stdprometheus "github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/go-kit/kit/log"
	kitprometheus "github.com/go-kit/kit/metrics/prometheus"
	httptransport "github.com/go-kit/kit/transport/http"
)

func main() {
	// когда я добавлял клиент для базы я не добавлял его в gopkg.toml пока плохо понимаю как управлять зависимости в этом менеджере пакетов
	// но если сделать:
	// dep ensure
	// go run flow/*.go находясь терминалом в noetl папке
	// go run flow/main.go работать не будет(( хоть в ветке Алексея она работала в чем разница такая?
	// todo 0) тут стартует инициализация аналитики prometheus и логера
	logger := log.NewLogfmtLogger(os.Stderr)

	fieldKeys := []string{"method", "error"}
	requestCount := kitprometheus.NewCounterFrom(stdprometheus.CounterOpts{
		Namespace: "my_group",
		Subsystem: "flow_service",
		Name:      "request_count",
		Help:      "Number of requests received.",
	}, fieldKeys) // аналитика количества обращений
	requestLatency := kitprometheus.NewSummaryFrom(stdprometheus.SummaryOpts{
		Namespace: "my_group",
		Subsystem: "flow_service",
		Name:      "request_latency_microseconds",
		Help:      "Total duration of requests in microseconds.",
	}, fieldKeys) // аналитика продолжительности выполнения запросов
	countResult := kitprometheus.NewSummaryFrom(stdprometheus.SummaryOpts{
		Namespace: "my_group",
		Subsystem: "flow_service",
		Name:      "count_result",
		Help:      "The result of each count method.",
	}, []string{}) // no fields here

	var flowServiceObject IFlow
	// тут мы инициализируем наш сервис как структуру
	flowServiceObject = flowService{}
	flowServiceObject = loggingMiddleware{logger, flowServiceObject} // прошу обратить внимание что next тут есть ссылка на наш обьект сервиса
	flowServiceObject = instrumentingMiddleware{requestCount, requestLatency, countResult, flowServiceObject} // прошу обратить внимание что next тут есть ссылка на обьект loggingMiddleware
	// функции миделвар должны называтся также чтобы можно было их так подключать в любом порядке
	// в итоге эти миделвары свернутся в defer для метода FlowPut который находится в файле service.go
	// Я пока писал это описание только понял в корне как оно работает.
	// мне показалось такая реализация мидевар сложновата и мы в каждой миделваре явно вызываем следующюю миделвару если функцию миделвары переименовать то цепочка оборвется
	// todo Существуют ли способы попроще для реализации этих вещей?
	flowHandler := httptransport.NewServer(
		makeFlowPutEndpoint(flowServiceObject),
		decodeFlowPutRequest,
		encodeResponse,
	)


	// todo сейчас этот запрос работает вот таким образом
	//MacBook-Pro-Yatsina:noetl yatsinaserhii$ curl -XPOST -d'{"id":"templates/directory1/demo1", "config": "содержимое конфига"}' localhost:8080/flow
	//{"success":true}
	//MacBook-Pro-Yatsina:noetl yatsinaserhii$ curl -XPUT -d'{"id":"templates/directory1/demo1", "config": "содержимое конфига"}' localhost:8080/flow
	//{"success":true}
	//MacBook-Pro-Yatsina:noetl yatsinaserhii$ curl -XGET -d'{"id":"templates/directory1/demo1", "config": "содержимое конфига"}' localhost:8080/flow
	//{"success":true}
	// как видем нам на патерне /flow нужно только PUT остальные пусть 500тят
	// todo Все это работает сейчас так:
	// todo 1) когда мы вызываем
	// curl -X{не важно какой метод} -d'{"id":"templates/directory1/demo1", "config": "содержимое конфига"}' localhost:8080/flow
	// вызывается
	http.Handle("/flow", flowHandler)






	// todo нам нужно обработать options запросы с браузера еще для всех запросов с админки UI
	// https://stackoverflow.com/questions/22972066/how-to-handle-preflight-cors-requests-on-a-go-server#answer-49213333
	http.Handle("/metrics", promhttp.Handler())
	logger.Log("msg", "HTTP", "addr", ":8080")
	logger.Log("err", http.ListenAndServe(":8080", nil))
}
