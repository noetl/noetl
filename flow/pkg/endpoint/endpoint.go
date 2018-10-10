package endpoint

import (
	"context"
	endpoint "github.com/go-kit/kit/endpoint"
	service "noetl/flow/pkg/service"
)

// ConfigRequest collects the request parameters for the Config method.
type ConfigRequest struct {
	S string `json:"s"`
}

// ConfigResponse collects the response parameters for the Config method.
type ConfigResponse struct {
	Rs  string `json:"rs"`
	Err error  `json:"err"`
}

// MakeConfigEndpoint returns an endpoint that invokes Config on the service.
func MakeConfigEndpoint(s service.FlowService) endpoint.Endpoint {
	return func(ctx context.Context, request interface{}) (interface{}, error) {
		req := request.(ConfigRequest)
		rs, err := s.Config(ctx, req.S)
		return ConfigResponse{
			Err: err,
			Rs:  rs,
		}, nil
	}
}

// Failed implements Failer.
func (r ConfigResponse) Failed() error {
	return r.Err
}

// Failer is an interface that should be implemented by response types.
// Response encoders can check if responses are Failer, and if so they've
// failed, and if so encode them using a separate write path based on the error.
type Failure interface {
	Failed() error
}

// Config implements Service. Primarily useful in a client.
func (e Endpoints) Config(ctx context.Context, s string) (rs string, err error) {
	request := ConfigRequest{S: s}
	response, err := e.ConfigEndpoint(ctx, request)
	if err != nil {
		return
	}
	return response.(ConfigResponse).Rs, response.(ConfigResponse).Err
}
