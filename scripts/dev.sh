function last-pod-logs() {
    kubectl get pods --sort-by=.metadata.creationTimestamp --selector=$1 --no-headers -o custom-columns=":metadata.name"
    POD=$(kubectl get pods --sort-by=.metadata.creationTimestamp --selector=$1 --no-headers -o custom-columns=":metadata.name" | tail -n1)

    kubectl logs -f ${POD} $2
}

function webhook-update() {
    minikube image build . -t erigrid/netem
    kubectl rollout restart deployment k8s-netem-webhook
    kubectl rollout status deployment k8s-netem-webhook

    webhook-logs
}


function example-run() {
    minikube image build . -t erigrid/netem

    kubectl rollout restart deployment example
    kubectl rollout status deployment example

    example-logs
}

function example-logs() {
    last-pod-logs component=example k8s-netem
}

function webhook-logs() {
    last-pod-logs app=k8s-netem-webhook
}
