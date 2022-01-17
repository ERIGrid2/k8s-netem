# k8s-netem

## Requirements

- System utilities
  - `nft` nftables
- Kernel modules
  - `ifb`
  - `sch_netem`

## Documentation

TODO

## Development setup

### Initial setup

```bash
minikube start
source scripts/dev.sh

kubectl create ns riasc-system

# Create self-signed certificate for mutating webhook
create-webhook-cert

# Build k8s-netem Docker image
build-image

# Add custom resource description for TrafficProfile resources
kubectl apply -f kubernetes/crd.yaml

# Register mutating webhook
kubectl -n riasc-system apply -f kubernetes/rbac.yaml
kubectl -n riasc-system apply -f kubernetes/deployment.yaml
kubectl -n riasc-system apply -f kubernetes/service.yaml
kubectl apply -f kubernetes/webhook.yaml
```

### Usage

```bash
source scripts/dev.sh

kubectl create ns my-app

# Create the example deployment and profile only for the first time
kubectl -n my-app apply -f kubernetes/example/profile.yaml
kubectl -n my-app apply -f kubernetes/example/deployment.yaml

# Rebuild k8s-netem Docker image and restart example deployment
example-run

# Use the following commands to inspect the logs of the example deployment and webhook
webhook-logs
sidecar-logs
example-logs ping-cloudflare
example-logs ping-google
```

## License

`k8s-netem` is licensed under the Apache 2.0 license.
Please refer to the `LICENSE.md` file for details.

## Credits

- Steffen Vogel <svogel2@eonerc.rwth-aachen.de> (RWTH Aachen University)
