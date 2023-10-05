# Deploy NATS

brew install jq
brew install kubectl
brew install kubectx
brew install fluxctl
brew install helm
brew tap nats-io/nats-tools              
brew install nats-io/nats-tools/nats

 ./deploy.sh

$ kubectl get svc -n nats 
NAME            TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)                      AGE
nats            NodePort    10.109.178.178   <none>        4222:30518/TCP               4m12s
nats-headless   ClusterIP   None             <none>        4222/TCP,6222/TCP,8222/TCP   4m12s
