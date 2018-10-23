package main

import (
	"errors"
)

// IFlow это интерфейс нашего сервиса Flow
type IFlow interface {

	FlowPut(flowPutRequest) (bool, error)
}

type flowService struct{}
// эта функция есть бизнес логика для записи наших конфигов в базу данных
func (flowService) FlowPut(conf flowPutRequest) (bool, error) {
	if conf.Id == "" { // если пришел пустой id
		return false, errors.New("flow Id should not be empty")
	}

	// todo 4) тут наша бизнес логика (а именно сохраняем в базу данных наш конфиг)
	// etcdDataBaseClientApi это ссылка на методы работы с базой смотреть фаил noetl/flow/etcd.go
	// etcd.go (внем просто примеры как ее использовать наш конечный код не обязательно там должен быть)
	// etcdDataBaseClientApi.Put(ctx, conf.Id, conf.config)
	// пример etcdDataBaseClientApi.Put(ctx, "/templates/directory1/demo1", "содержимое конфига который в demo1")
	// эта команда сохранит конфиг по id /templates/directory1/demo1 причем если этого конфига нету метод put сам его стоздаст в базе
	// а если id есть то пишет в него не перезаписывая а ведя историю изменений конфига
	// подробнее можно почитать о клиенте для базы тут https://github.com/etcd-io/etcd/tree/master/clientv3
	return true, nil
}
