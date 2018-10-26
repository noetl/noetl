package flow

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/gorilla/mux"
	"net/http"

	"github.com/go-kit/kit/endpoint"
	kitlog "github.com/go-kit/kit/log"
	kithttp "github.com/go-kit/kit/transport/http"
)

type flowPutRequest struct {
	Id     string `json:"id"`
	Config string `json:"config"`
}

type flowPutResponse struct {
	Success bool   `json:"success"`
	Err     string `json:"err,omitempty"`
}

func makeFlowPutEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		// todo 3) тут мы возвращаем конечную точку достуа а именно принимаем раскодированый json и вызываем метод нашей бизнес логики
		req := request.(flowPutRequest)
		Success, err := svc.FlowPut(req)
		if err != nil {
			return flowPutResponse{Success, err.Error()}, nil
		}
		return flowPutResponse{Success, ""}, nil
		// и возвращаем ответ для фронтенда (тут мы возвращаем структуру она преобразуется в json в методе encodeResponse() 34 строчка)
	}
}

func encodeResponse(_ context.Context, w http.ResponseWriter, response interface{}) error {
	// todo 5) тут мы собираем наш ответ для UI в json формат ответ который вернет функция makeFlowPutEndpoint 21 я строка
	return json.NewEncoder(w).Encode(response)
}

func decodeFlowPutRequest(_ context.Context, r *http.Request) (interface{}, error) {
	// todo 2) тут мы раскодируем тело запроса
	var request flowPutRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}

type flowGetRequest struct {
	Id string
}

type flowGetResponse struct {
	Success bool   `json:"success"`
	Config  string `json:"config"`
}

func makeFlowGetEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		fmt.Println(request)
		req := request.(flowGetRequest)
		Config, err := svc.FlowGet(req.Id)
		if err != nil {
			return flowPutResponse{false, err.Error()}, nil
		}
		return flowGetResponse{true, Config}, nil
		// и возвращаем ответ для фронтенда (тут мы возвращаем структуру она преобразуется в json в методе encodeResponse() 34 строчка)
	}
}

var errBadRoute = errors.New("bad route")
func decodeFlowGetRequest(_ context.Context, r *http.Request) (interface{}, error) {
	vars := mux.Vars(r)
	id, ok := vars["id"]
	if !ok {
		return nil, errBadRoute
	}
	return flowGetRequest{Id: id}, nil
}


// MakeHandler returns a handler for the booking service.
func MakeHandler(s Service, logger kitlog.Logger) http.Handler {
	opts := []kithttp.ServerOption{
		kithttp.ServerErrorLogger(logger),
		kithttp.ServerErrorEncoder(encodeError),
	}

	flowPutHandler := kithttp.NewServer(
		makeFlowPutEndpoint(s),
		decodeFlowPutRequest,
		encodeResponse,
		opts...,
	)

	flowGetHandler := kithttp.NewServer(
		makeFlowGetEndpoint(s),
		decodeFlowGetRequest,
		encodeResponse,
		opts...,
	)

	r := mux.NewRouter()

	//r.Handle("/flow/v1/template", bookCargoHandler).Methods("POST")
	r.Handle("/flow/v1/template", flowPutHandler).Methods("PUT")
	r.Handle("/flow/v1/template/{id}", flowGetHandler).Methods("GET")

	return r
}
// encode errors from business-logic
func encodeError(_ context.Context, err error, w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	switch err {
	case ErrInvalidArgument:
		w.WriteHeader(http.StatusBadRequest)
	default:
		w.WriteHeader(http.StatusInternalServerError)
	}
	json.NewEncoder(w).Encode(map[string]interface{}{
		"error": err.Error(),
	})
}
