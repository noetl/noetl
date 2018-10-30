package flow

import (
	"context"
	"encoding/json"
	"github.com/gorilla/mux"
	"github.com/pkg/errors"
	"net/http"
	"github.com/go-kit/kit/endpoint"
	kitlog "github.com/go-kit/kit/log"
	kithttp "github.com/go-kit/kit/transport/http"
)

type flowsDirectoryDeleteRequest struct {
	// config id
	Path     string `json:"path"`
}

type flowsDirectoryDeleteResponse struct {
	// is successfully request
	Success bool `json:"success"`
}

func makeFlowsDirectoryDeleteEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowsDirectoryDeleteRequest)
		success, err := svc.FlowsDirectoryDelete(req)
		if err != nil {
			return nil, err
		}
		return flowsDirectoryDeleteResponse{success}, nil
	}
}

func decodeFlowsDirectoryDeleteRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowsDirectoryDeleteRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, errors.Wrap(err, "wrong json format")
	}
	return request, nil
}

type flowDeleteRequest struct {
	// config id
	Id     string `json:"id"`
}

type flowDeleteResponse struct {
	// is successfully request
	Success bool `json:"success"`
}

func makeFlowDeleteEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowDeleteRequest)
		success, err := svc.FlowDelete(req)
		if err != nil {
			return nil, err
		}
		return flowDeleteResponse{success}, nil
	}
}

func decodeFlowDeleteRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowDeleteRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, errors.Wrap(err, "wrong json format")
	}
	return request, nil
}

type flowPostRequest struct {
	// config id
	Id     string `json:"id"`
	// configuration contents
	Config string `json:"config"`
}

type flowPostResponse struct {
	// is successfully request
	Success bool `json:"success"`
}

func makeFlowPostEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowPostRequest)
		success, err := svc.FlowPost(req)
		if err != nil {
			return nil, err
		}
		return flowPostResponse{success}, nil
	}
}

func decodeFlowPostRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowPostRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, errors.Wrap(err, "wrong json format")
	}
	return request, nil
}

type flowPutRequest struct {
	// config id
	Id     string `json:"id"`
	// configuration contents
	Config string `json:"config"`
}

type flowPutResponse struct {
	// is successfully request
	Success bool `json:"success"`
}

func makeFlowPutEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowPutRequest)
		success, err := svc.FlowPut(req)
		if err != nil {
			return nil, err
		}
		return flowPutResponse{success}, nil
	}
}

func decodeFlowPutRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowPutRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, errors.Wrap(err, "wrong json format")
	}
	return request, nil
}

type flowGetRequest struct {
	// config id
	Id string `json:"id"`
}

type flowGetResponse struct {
	// is successfully request
	Success bool   `json:"success"`
	// configuration contents
	Config  string `json:"config"`
}

func makeFlowGetEndpoint(svc Service) endpoint.Endpoint {
	return func(_ context.Context, request interface{}) (interface{}, error) {
		req := request.(flowGetRequest)
		config, err := svc.FlowGet(req.Id)
		if err != nil {
			return nil, err
		}
		return flowGetResponse{true, config}, nil
	}
}

func decodeFlowGetRequest(_ context.Context, r *http.Request) (interface{}, error) {
	var request flowGetRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, errors.Wrap(err, "wrong json format")
	}
	return request, nil
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

	flowsDirectoryDeleteHandler := kithttp.NewServer(
		makeFlowsDirectoryDeleteEndpoint(s),
		decodeFlowsDirectoryDeleteRequest,
		encodeResponse,
		opts...,
	)

	r := mux.NewRouter()
	r.Handle("/flow/v1/templates", flowsDirectoryDeleteHandler).Methods("DELETE")
	r.Handle("/flow/v1/template", flowDeleteHandler).Methods("DELETE")
	r.Handle("/flow/v1/template", flowPostHandler).Methods("POST")
	r.Handle("/flow/v1/template", flowPutHandler).Methods("PUT")
	r.Handle("/flow/v1/template", flowGetHandler).Methods("GET")

	return r
}

func encodeResponse(_ context.Context, w http.ResponseWriter, response interface{}) error {
	return json.NewEncoder(w).Encode(response)
}

// error response for all request
type failureResponse struct {
	// is successfully request
	Success bool   `json:"success"`
	Err     string `json:"error,omitempty"`
}

func encodeError(_ context.Context, err error, w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(failureResponse{false, err.Error()})
}
