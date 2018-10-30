package flow

import (
	"context"
	"encoding/json"
	"github.com/gorilla/mux"
	"net/http"

	"github.com/go-kit/kit/endpoint"
	kitlog "github.com/go-kit/kit/log"
	kithttp "github.com/go-kit/kit/transport/http"
)

// flowDelete
type flowDeleteRequest struct {
	Id     string `json:"id"`
}

type flowDeleteResponse struct {
	Success bool `json:"success"`
}

func makeFlowDeleteEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowDeleteRequest)
		Success, err := svc.FlowDelete(req)
		if err != nil {
			return nil, err
		}
		return flowDeleteResponse{Success}, nil
	}
}

func decodeFlowDeleteRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowDeleteRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}

// flowPost
type flowPostRequest struct {
	Id     string `json:"id"`
	Config string `json:"config"`
}

type flowPostResponse struct {
	Success bool `json:"success"`
}

func makeFlowPostEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowPostRequest)
		Success, err := svc.FlowPost(req)
		if err != nil {
			return nil, err
		}
		return flowPostResponse{Success}, nil
	}
}

func decodeFlowPostRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowPostRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}

// flowPut
type flowPutRequest struct {
	Id     string `json:"id"`
	Config string `json:"config"`
}

type flowPutResponse struct {
	Success bool `json:"success"`
}

func makeFlowPutEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowPutRequest)
		Success, err := svc.FlowPut(req)
		if err != nil {
			return nil, err
		}
		return flowPutResponse{Success}, nil
	}
}

func decodeFlowPutRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowPutRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}

// flowGet
type flowGetRequest struct {
	Id string `json:"id"`
}

type flowGetResponse struct {
	Success bool   `json:"success"`
	Config  string `json:"config"`
}

func makeFlowGetEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowGetRequest)
		Config, err := svc.FlowGet(req.Id)
		if err != nil {
			return nil, err
		}
		return flowGetResponse{true, Config}, nil
	}
}

func decodeFlowGetRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowGetRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}

/* example for routing treatment
var errBadRoute = errors.New("bad route")
func decodeFlowGetRequest(_ context.Context, r *http.Request) (interface{}, error) {
	vars := mux.Vars(r)
	id, ok := vars["id"]
	if !ok {
		return nil, errBadRoute
	}
	return flowGetRequest{Id: id}, nil
}
*/

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

	flowPostHandler := kithttp.NewServer(
		makeFlowPostEndpoint(s),
		decodeFlowPostRequest,
		encodeResponse,
		opts...,
	)

	flowDeleteHandler := kithttp.NewServer(
		makeFlowDeleteEndpoint(s),
		decodeFlowDeleteRequest,
		encodeResponse,
		opts...,
	)

	r := mux.NewRouter()

	r.Handle("/flow/v1/template", flowDeleteHandler).Methods("DELETE")
	r.Handle("/flow/v1/template", flowPostHandler).Methods("POST")
	r.Handle("/flow/v1/template", flowPutHandler).Methods("PUT")
	r.Handle("/flow/v1/template", flowGetHandler).Methods("GET")

	return r
}

// for all requests
func encodeResponse(_ context.Context, w http.ResponseWriter, response interface{}) error {
	return json.NewEncoder(w).Encode(response)
}

// encode errors from business-logic
type failureResponse struct {
	Success bool   `json:"success"`
	Err     string `json:"error,omitempty"`
}

func encodeError(_ context.Context, err error, w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(failureResponse{false, err.Error()})
}
