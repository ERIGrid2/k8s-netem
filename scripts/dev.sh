NS=riasc-system
NS_USER=my-app

KUBECTL="kubectl -n ${NS}"
KUBECTL_USER="kubectl -n ${NS_USER}"

function create-webhook-cert() {
    openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 3650 -config scripts/req.conf -extensions 'v3_req'

    ${KUBECTL} delete secret k8s-netem-webhook-certs > /dev/null 2>&1 || true
    ${KUBECTL} create secret tls k8s-netem-webhook-certs --cert=cert.pem --key=key.pem

    CA_BUNDLE=$(base64 -w0 < cert.pem)

    echo "caBundle value: ${CA_BUNDLE}"

    sed -i .bak -e "s/caBundle: \(.*\)/caBundle: ${CA_BUNDLE}/g" kubernetes/webhook.yaml
}

function build-image() {
    minikube image build . -t erigrid/netem:latest
}

function last-pod-logs() {
    POD=$(kubectl -n $1 get pods --sort-by=.metadata.creationTimestamp --selector=$2 --no-headers -o custom-columns=":metadata.name" | tail -n1)

    kubectl -n $1 logs -f ${POD} $3
}

function webhook-run() {
    build-image

    ${KUBECTL} rollout restart deployment k8s-netem-webhook
    ${KUBECTL} rollout status deployment k8s-netem-webhook

    webhook-logs
}

function example-run() {
    build-image

    ${KUBECTL_USER} rollout restart deployment example
    ${KUBECTL_USER} rollout status deployment example

    example-logs
}

function example-logs() {
    last-pod-logs ${NS_USER} component=example $1
}

function sidecar-logs() {
    last-pod-logs ${NS_USER} component=example k8s-netem
}

function webhook-logs() {
    last-pod-logs ${NS} app=k8s-netem-webhook
}
