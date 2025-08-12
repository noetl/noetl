# Kubernetes Dashboard

The Kubernetes Dashboard is a web-based UI for Kubernetes clusters. It allows to deploy containerized applications to a Kubernetes cluster, troubleshoot containerized application, and manage the cluster resources.

Note: The Dashboard is NOT installed by default by this repository's scripts or manifests.

## Installation

Install the official Dashboard resources (check the official docs for the latest version):

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml
```

Optional (but recommended): install metrics-server if you want resource metrics to appear in the Dashboard:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

## Accessing the Dashboard

To access the Kubernetes Dashboard, follow these steps:

1. Start the Kubernetes proxy:
   ```bash
   kubectl proxy
   ```
   This command will start a proxy server running on local machine that will securely communicate with the Kubernetes API server.

2. Access the Dashboard at the following URL:
   ```
   http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
   ```

3. You will be presented with a login screen. You can authenticate using:
   - A token
   - A kubeconfig file

## Creating a Service Account for Dashboard Access

For security reasons, it's recommended to create a dedicated service account with appropriate permissions:
1. Create a service account in the kubernetes-dashboard namespace
```bash
kubectl create serviceaccount dashboard-admin-sa -n kubernetes-dashboard
```

2. Create a cluster role binding for the service account
```bash
kubectl create clusterrolebinding dashboard-admin-sa \
  --clusterrole=cluster-admin \
  --serviceaccount=kubernetes-dashboard:dashboard-admin-sa
```

3. If cluster supports 'kubectl create token', use this command to create a token:
```bash
kubectl -n kubernetes-dashboard create token dashboard-admin-sa
```

4. If cluster doesn't support `kubectl create token`, use this fallback to extract from a Secret:  
```bash
TOKEN_NAME=$(kubectl -n kubernetes-dashboard get sa/dashboard-admin-sa -o jsonpath="{.secrets[0].name}")
kubectl -n kubernetes-dashboard get secret "$TOKEN_NAME" -o jsonpath="{.data.token}" | base64 --decode && echo
```

Use the token displayed in the output to log in to the Dashboard.

## Features

The Kubernetes Dashboard provides:

- Deployment management
- Resource monitoring
- Error identification and troubleshooting
- Overview of applications running on the cluster
- Creating and modifying individual Kubernetes resources

## Security Considerations

The Kubernetes Dashboard is a powerful tool that provides full administrative access to cluster. Consider the following security practices:

1. Only expose the Dashboard within trusted networks
2. Use RBAC to limit access to specific resources
3. Consider using read-only access for regular users
4. Avoid exposing the Dashboard to the public internet

## Troubleshooting

If you encounter issues accessing the Dashboard:

1. Ensure the proxy is running
2. Check that the Dashboard pods are running:
   ```bash
   kubectl get pods -n kubernetes-dashboard
   ```
3. Check the Dashboard logs:
   ```bash
   kubectl logs -n kubernetes-dashboard -l k8s-app=kubernetes-dashboard
   ```

## Additional Resources

- [Kubernetes Dashboard GitHub Repository](https://github.com/kubernetes/dashboard)
- [Official Documentation](https://kubernetes.io/docs/tasks/access-application-cluster/web-ui-dashboard/)