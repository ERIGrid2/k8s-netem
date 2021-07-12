#!/bin/sh

openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 3650 -subj "/C=DE/ST=NRW/L=Aachen/CN=k8s-netem-webhook.riasc-system.svc"

kubectl -n riasc-system delete secret k8s-netem-webhook-certs || true
kubectl -n riasc-system create secret tls k8s-netem-webhook-certs --cert=cert.pem --key=key.pem 

echo "caBundle value: "
base64 -w0 < cert.pem

rm cert.pem key.pem
