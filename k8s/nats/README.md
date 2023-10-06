## Deploy NATS

### Install Helm
```
brew install helm
```

### Install nats CLI tool
```
brew tap nats-io/nats-tools
brew install nats-io/nats-tools/nats
```

### Install `kubectl` and `kubectx`
```
brew install kubectl
brew install kubectx
```

### Add Helm nats repository
```
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
```

### Switch to `docker-desktop` context for working with Docker Kubernetes cluster
```
kubectx docker-desktop
```

### Install nats Helm chart
```
helm install nats nats/nats \
    --values values.yaml \
    --namespace nats --create-namespace
```
The command should be executed from `noetl/k8s/nats`, otherwise the full path to the `values.yaml` should be specified. The chart will be installed in the `nats` namespace.

**Check the pods in the `nats` namespace and wait until all containers in the pods are ready**
```
% kubectl get pod -n nats                                                      
NAME                        READY   STATUS    RESTARTS   AGE
nats-0                      2/2     Running   0          37m
nats-1                      2/2     Running   0          37m
nats-box-75cdf6b96c-jqfkc   1/1     Running   0          37m
```

**Check services in the `nats` namespace**
```
% kubectl get svc -n nats
NAME            TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)                         AGE
nats            NodePort    10.101.227.169   <none>        4222:30867/TCP,8222:30138/TCP   39m
nats-headless   ClusterIP   None             <none>        4222/TCP,6222/TCP,8222/TCP      39m
```
Note the exposed **NodePort**s for access to the nats.
In the example above the port **30867** is for access to the nats and the port **30138** is for monitoring.

If everything is installed correctly you will be able to open the following address in a WEB browser to check `nats` configuration: http://localhost:30138/.  
Or check, for instance, `jetstream` settings with `curl` command.
```
% curl http://localhost:30138/jsz
{
  "server_id": "NBIYRUPVVMYXF5YOYMIX6V6JNESY575VMEHZRJKL4WH6RYNGXZHNHPRA",
  "now": "2023-10-05T13:10:24.459826626Z",
  "config": {
    "max_memory": 0,
    "max_storage": 10737418240,
    "store_dir": "/data/jetstream",
    "sync_interval": 120000000000
  },
  "memory": 0,
  "storage": 0,
  "reserved_memory": 0,
  "reserved_storage": 0,
  "accounts": 1,
  "ha_assets": 1,
  "api": {
    "total": 4,
    "errors": 0
  },
  "streams": 0,
  "consumers": 0,
  "messages": 0,
  "bytes": 0,
  "meta_cluster": {
    "name": "nats",
    "leader": "nats-0",
    "peer": "S1Nunr6R",
    "replicas": [
      {
        "name": "nats-1",
        "current": true,
        "active": 593638792,
        "peer": "yrzKKRBu"
      }
    ],
    "cluster_size": 2
  }
}% 
```
  
Streams and Consumers can be created with JetStream Controller
## Install JetStream Controller and create Streams and Consumers

### Install the JetStream CRDs:
```
kubectl apply -f https://github.com/nats-io/nack/releases/latest/download/crds.yml
```

### Install the JetStream controller Helm chart:
```
helm install nack nats/nack --set jetstream.nats.url=nats://nats:4222 -n nats
```

### Create Stream
```
kubectl apply -f stream.yaml -n nats 
```
### Check that Stream is successfully created
With `kubectl`
```
% kubectl get stream -n nats
NAME       STATE     STREAM NAME   SUBJECTS
hogwarts   Created   hogwarts      ["magic.*"]
```
Or with `nats` CLI
```
% nats stream ls -s nats://localhost:30867
╭──────────────────────────────────────────────────────────────────────────────────╮
│                                      Streams                                     │
├──────────┬─────────────┬─────────────────────┬──────────┬─────────┬──────────────┤
│ Name     │ Description │ Created             │ Messages │ Size    │ Last Message │
├──────────┼─────────────┼─────────────────────┼──────────┼─────────┼──────────────┤
│ hogwarts │             │ 2023-10-05 18:26:06 │ 30       │ 2.6 KiB │ 11m0s        │
╰──────────┴─────────────┴─────────────────────┴──────────┴─────────┴──────────────╯
```


### Create Consumers
```
kubectl apply -f consumer1-pull.yaml -n nats
kubectl apply -f consumer2-pull.yaml -n nats
kubectl apply -f consumer-push.yaml -n nats
```
Additional information about consumres can be found here:  

Push Consumers - https://natsbyexample.com/examples/jetstream/push-consumer/go  
Pull Consumers - https://natsbyexample.com/examples/jetstream/pull-consumer/go

### Check that Consumers are successfully created
With `kubectl`
```
% kubectl get consumers -n nats
NAME              STATE     STREAM     CONSUMER          ACK POLICY
dumbledore-pull   Created   hogwarts   dumbledore-pull   explicit
harry-push        Created   hogwarts   harry-push        none
hermione-pull     Created   hogwarts   hermione-pull     explicit
```
Or with `nats` CLI
```
% nats consumer ls hogwarts -s nats://localhost:30867
Consumers for Stream hogwarts:

	dumbledore-pull
	harry-push
	hermione-pull
```

### Check the messaging

Create additional terminal to read data using a push-based consumer. Run the following command.
```
nats sub harry-push.magic -s nats://localhost:30867
```
Now generate the message sequence for the `magic.*` subject which belongs to the created stream.
```
% nats pub magic.spell --count=10 --sleep 1s "expecto patronum #{{Count}} @ {{TimeStamp}}" -s nats://localhost:30867
19:48:21 Published 47 bytes to "magic.spell"
19:48:22 Published 47 bytes to "magic.spell"

---output omitted---
```
The messages should appear in the terminal where the push consumer is running.
```
% nats sub harry-push.magic -s nats://localhost:30867                    
19:47:54 Subscribing on harry-push.magic 
[#1] Received JetStream message: consumer: hogwarts > harry-push / subject: magic.spell / delivered: 1 / consumer seq: 1 / stream seq: 31
expecto patronum #1 @ 2023-10-05T19:48:20+05:00


[#2] Received JetStream message: consumer: hogwarts > harry-push / subject: magic.spell / delivered: 1 / consumer seq: 2 / stream seq: 32
expecto patronum #2 @ 2023-10-05T19:48:21+05:00

---output omitted---
```
Read the messages with pull consumer.
```
nats consumer next hogwarts hermione-pull --count 5  -s nats://localhost:30867
[19:51:02] subj: magic.spell / tries: 1 / cons seq: 1 / str seq: 31 / pending: 9

expecto patronum #1 @ 2023-10-05T19:48:20+05:00

Acknowledged message

[19:51:02] subj: magic.spell / tries: 1 / cons seq: 2 / str seq: 32 / pending: 8

---output omitted---
```
5 messages should be read. If the command executed once again the next 5 messages will be read.
```
% nats consumer next hogwarts hermione-pull --count 5  -s nats://localhost:30867
[19:52:48] subj: magic.spell / tries: 1 / cons seq: 6 / str seq: 36 / pending: 4

expecto patronum #6 @ 2023-10-05T19:48:25+05:00

Acknowledged message

[19:52:48] subj: magic.spell / tries: 1 / cons seq: 7 / str seq: 37 / pending: 3

expecto patronum #7 @ 2023-10-05T19:48:26+05:00

---output omitted---
```

Read messages from the stream with second pull consumer.
```
% nats consumer next hogwarts dumbledore-pull --count 5  -s nats://localhost:30867
[19:53:59] subj: magic.spell / tries: 1 / cons seq: 1 / str seq: 31 / pending: 9

expecto patronum #1 @ 2023-10-05T19:48:20+05:00

Acknowledged message

[19:53:59] subj: magic.spell / tries: 1 / cons seq: 2 / str seq: 32 / pending: 8

expecto patronum #2 @ 2023-10-05T19:48:21+05:00

---output omitted---
```
Note that reading started from the beginning of the stream.
