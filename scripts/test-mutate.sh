#!/bin/bash

cat > pod.json <<EOF
{
    "request": {
        "uid": "eb6a1f44-e2fd-11eb-8d99-7c507989889d",
        "object": {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "example",
                "labels": {
                "component": "test",
                "traffic-profile": "delay-jitter-to-quad-one"
                }
            },
            "spec": {
                "containers": [
                    {
                        "name": "busybox",
                        "image": "busybox:1.25",
                        "command": [
                        "ping",
                        "1.1.1.1"
                        ]
                    }
                ]
            }
        }
    }
}
EOF

curl -X POST \
    --data @pod.json \
    -H "Content-Type: application/json" \
    http://localhost:5000/mutate

rm pod.json
