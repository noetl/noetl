package main

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/go-kit/kit/endpoint"
)

type flowPutRequest struct {
	Id string `json:"id"`
	Config string `json:"config"`
}

type flowPutResponse struct {
	Success bool `json:"success"`
	Err string `json:"err,omitempty"`
}

func makeFlowPutEndpoint(svc IFlow) endpoint.Endpoint {
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
	// и в этом же файле описаны методы и структуры для раскодирования и заворачивание в json (вообщем все для транспорта)
	//switch r.Method {
	//case http.MethodGet:
	//	// Serve the resource.
	//case http.MethodPost:
	//	// Create a new record.
	//case http.MethodPut:
	//	// Update an existing record.
	//case http.MethodDelete:
	//	// Remove the record.
	//default:
	//	// Give an error message.
	//}
	var request flowPutRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		return nil, err
	}
	return request, nil
}






// эта структура для другого запроса которого еще нет не обращайте внимание
//type flowGetResponse struct {
//	Success bool `json:"success"`
//	Config string `json:"config,omitempty"`
//	Err string `json:"err,omitempty"`
//}




