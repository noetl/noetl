// todo Этот фаил являеется примером работы с etcd базой данных (здесь используется клиент github.com/coreos/etcd/clientv3) написаный для этой базы данных
// насколько я понял по исходникам внутри этого клиента используется протокол rpc.
// гугловый grpc тоже там есть но я не вникал используем мы этот grpc в нашем проекте при текущей конфигурации клиента
// если мы не хотим использовать этот клиент то можно общатся с базой напрямую (например по http это выглядит так https://poweruphosting.com/blog/etcd-tutorial/)
// https://github.com/etcd-io/etcd/tree/master/clientv3


package main

import (
	"fmt"
	"context"
	"log"
	"github.com/coreos/etcd/clientv3"
	"time"
	"strconv"
)

var (
	dialTimeout    = 2 * time.Second
	requestTimeout = 10 * time.Second
)

func GetSingleValueDemo(ctx context.Context, kv clientv3.KV) {
	fmt.Println("*** GetSingleValueDemo()")
	// Delete all keys
	kv.Delete(ctx, "key", clientv3.WithPrefix())

	// Insert a key value
	pr, err := kv.Put(ctx, "key", "444")
	if err != nil {
		log.Fatal(err)
	}

	rev := pr.Header.Revision

	fmt.Println("Revision:", rev)

	gr, err := kv.Get(ctx, "key")
	if err != nil {
		log.Fatal(err)
	}

	fmt.Println("Value: ", string(gr.Kvs[0].Value), "Revision: ", gr.Header.Revision)

	// Modify the value of an existing key (create new revision)
	kv.Put(ctx, "key", "555")

	gr, _ = kv.Get(ctx, "key")
	fmt.Println("Value: ", string(gr.Kvs[0].Value), "Revision: ", gr.Header.Revision)

	// Get the value of the previous revision
	gr, _ = kv.Get(ctx, "key", clientv3.WithRev(rev))
	fmt.Println("Value: ", string(gr.Kvs[0].Value), "Revision: ", gr.Header.Revision)
}

func GetMultipleValuesWithPaginationDemo(ctx context.Context, kv clientv3.KV) {
	fmt.Println("*** GetMultipleValuesWithPaginationDemo()")
	// Delete all keys
	kv.Delete(ctx, "key", clientv3.WithPrefix())

	// Insert 50 keys
	for i := 0; i < 50; i++ {
		k := fmt.Sprintf("key_%02d", i)
		kv.Put(ctx, k, strconv.Itoa(i))
	}

	opts := []clientv3.OpOption{
		clientv3.WithPrefix(),
		clientv3.WithSort(clientv3.SortByKey, clientv3.SortAscend),
		clientv3.WithLimit(10),
	}

	gr, err := kv.Get(ctx, "key", opts...)
	if err != nil {
		log.Fatal(err)
	}

	fmt.Println("--- First page ---")
	for _, item := range gr.Kvs {
		fmt.Println(string(item.Key), string(item.Value))
	}

	lastKey := string(gr.Kvs[len(gr.Kvs)-1].Key)

	fmt.Println("--- Second page ---")
	opts = append(opts, clientv3.WithFromKey())
	gr, _ = kv.Get(ctx, lastKey, opts...)

	// Skipping the first item, which the last item from from the previous Get
	for _, item := range gr.Kvs[1:] {
		fmt.Println(string(item.Key), string(item.Value))
	}
}

func WatchDemo(ctx context.Context, cli *clientv3.Client, kv clientv3.KV) {
	fmt.Println("*** WatchDemo()")
	// Delete all keys
	kv.Delete(ctx, "key", clientv3.WithPrefix())

	stopChan := make(chan interface{})
	go func() {
		watchChan := cli.Watch(ctx, "key", clientv3.WithPrefix())
		for true {
			select {
			case result := <-watchChan:
				for _, ev := range result.Events {
					fmt.Printf("%s %q : %q\n", ev.Type, ev.Kv.Key, ev.Kv.Value)
				}
			case <-stopChan:
				fmt.Println("Done watching.")
				return
			}
		}
	}()

	// Insert some keys
	for i := 0; i < 10; i++ {
		k := fmt.Sprintf("key_%02d", i)
		kv.Put(ctx, k, strconv.Itoa(i))
	}

	// Make sure watcher go routine has time to recive PUT events
	time.Sleep(time.Second)

	stopChan <- 1

	// Insert some more keys (no one is watching)
	for i := 10; i < 20; i++ {
		k := fmt.Sprintf("key_%02d", i)
		kv.Put(ctx, k, strconv.Itoa(i))
	}
}

func LeaseDemo(ctx context.Context, cli *clientv3.Client, kv clientv3.KV) {
	fmt.Println("*** LeaseDemo()")
	// Delete all keys
	kv.Delete(ctx, "key", clientv3.WithPrefix())

	gr, _ := kv.Get(ctx, "key")
	if len(gr.Kvs) == 0 {
		fmt.Println("No 'key'")
	}


	lease, err := cli.Grant(ctx, 1)
	if err != nil {
		log.Fatal(err)
	}

	// Insert key with a lease of 1 second TTL
	kv.Put(ctx, "key", "value", clientv3.WithLease(lease.ID))

	gr, _ = kv.Get(ctx, "key")
	if len(gr.Kvs) == 1 {
		fmt.Println("Found 'key'")
	}

	// Let the TTL expire
	time.Sleep(3 * time.Second)

	gr, _ = kv.Get(ctx, "key")
	if len(gr.Kvs) == 0 {
		fmt.Println("No more 'key'")
	}
}

func main1() {

	ctx, _ := context.WithTimeout(context.Background(), 10 * time.Second) // for request Timeout
	etcdDataBaseClient, err := clientv3.New(clientv3.Config{
		DialTimeout: 2 * time.Second,
		Endpoints: []string{"127.0.0.1:2379"},
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
