function webhook-update() {
    minikube image build . -t erigrid/netem
    kubectl rollout restart deployment k8s-netem-webhook
    kubectl rollout status deployment k8s-netem-webhook

    webhook-logs
}

function webhook-logs() {
    kubectl get pods --sort-by=.metadata.creationTimestamp --selector=app=k8s-netem-webhook --no-headers -o custom-columns=":metadata.name"
    POD=$(kubectl get pods --sort-by=.metadata.creationTimestamp --selector=app=k8s-netem-webhook --no-headers -o custom-columns=":metadata.name" | tail -n1)

    kubectl logs -f ${POD} 
}
 
function run-example() {
    kubectl rollout restart deployment example
    kubectl rollout status deployment example
}
