// todo Этот фаил являеется примером работы с etcd базой данных (здесь используется клиент github.com/coreos/etcd/clientv3) написаный для этой базы данных
// насколько я понял по исходникам внутри этого клиента используется протокол rpc.
// гугловый grpc тоже там есть но я не вникал используем мы этот grpc в нашем проекте при текущей конфигурации клиента
// если мы не хотим использовать этот клиент то можно общатся с базой напрямую (например по http это выглядит так https://poweruphosting.com/blog/etcd-tutorial/)
// https://github.com/etcd-io/etcd/tree/master/clientv3

package flow

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/coreos/etcd/clientv3"
)

var (
	dialTimeout    = 2 * time.Second
	requestTimeout = 10 * time.Second
)

func main1() {

	ctx, _ := context.WithTimeout(context.Background(), 10*time.Second) // for request Timeout
	etcdDataBaseClient, err := clientv3.New(clientv3.Config{
		DialTimeout: 2 * time.Second,
		Endpoints:   []string{"127.0.0.1:2379"},
	})
	if err != nil {
		log.Fatal(err)
	}
	defer etcdDataBaseClient.Close()
	etcdDataBaseClientApi := clientv3.NewKV(etcdDataBaseClient)

	//GetSingleValueDemo(ctx, kv)
	//GetMultipleValuesWithPaginationDemo(ctx, kv)
	//WatchDemo(ctx, cli, kv)
	//LeaseDemo(ctx, cli, kv)

	etcdDataBaseClientApi.Put(ctx, "id нашего workflow (и оно не такое как в конфигурации самой так как содержит полный путь к нему) (например /templates/directory1/demo1 где demo1 это уникальное имя в пределах папки (directory1))", "содержимое конфигурации в строковом формате (например json)")

	opts := []clientv3.OpOption{
		clientv3.WithPrefix(),
		clientv3.WithSort(clientv3.SortByKey, clientv3.SortAscend),
		clientv3.WithLimit(10),
	}
	gr, err := etcdDataBaseClientApi.Get(ctx, "key", opts...)
	if err != nil {
		log.Fatal(err)
	}

	fmt.Println("--- First page ---")
	for _, item := range gr.Kvs {
		fmt.Println(string(item.Key), string(item.Value))
	}

	//gr, _ := kv.Get(ctx, "templates/directory1/demo1")
	//kv.Put(ctx, "/templates/directory1/demo1", "содержимое конфига который в demo1")
	//kv.Put(ctx, "/templates/directory1/demo2", "содержимое конфига который в demo2")
	//
	//kv.Put(ctx, "/templates-metatree", "metatree")
}
