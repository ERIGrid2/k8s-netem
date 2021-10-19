from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
import base64
import logging
import os
import os.path
import http
import json
import jsonpatch

from k8s_netem.profile import Profile

from kubernetes import client, config

SSL_CERT_FILE = os.environ.get('SSL_CERT_FILE', '/certs/tls.crt')
SSL_KEY_FILE = os.environ.get('SSL_KEY_FILE', '/certs/tls.key')

DEBUG = 'DEBUG' in os.environ

app = Flask(__name__)


def mutate_pod(pod):
    profiles = Profile.list()

    has_profiles = len([p for p in profiles if p.match(pod)]) > 0
    has_netem_container = len([c for c in pod.spec.containers
                              if c.name == 'k8s-netem']) > 0

    logging.info('Mutating pod')

    if has_profiles and not has_netem_container:
        env_vars = [
            {
                'name': 'POD_NAME',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'metadata.name'
                    }
                }
            },
            {
                'name': 'POD_NAMESPACE',
                'valueFrom': {
                    'fieldRef': {
                        'fieldPath': 'metadata.namespace'
                    }
                }
            }
        ]

        if DEBUG:
            env_vars.append({
                'name': 'DEBUG',
                'value': '1'
            })

        pod.spec.containers.append({
            'name': 'k8s-netem',
            'image': 'erigrid/netem',
            'imagePullPolicy': 'Never' if DEBUG else 'IfNotPresent',
            'env': env_vars
        })

        logging.info('Added netem sidecar to pod')


@app.route('/mutate', methods=['POST'])
def mutate():
    obj = request.json['request']['object']

    v1 = client.CoreV1Api()
    pod = v1.api_client._ApiClient__deserialize(obj, 'V1Pod')

    mutate_pod(pod)

    obj_modified = v1.api_client.sanitize_for_serialization(pod)

    patch = jsonpatch.JsonPatch.from_diff(obj, obj_modified)

    return jsonify({
        'apiVersion': 'admission.k8s.io/v1',
        'kind': 'AdmissionReview',
        'response': {
            'allowed': True,
            'uid': request.json['request']['uid'],
            'patch': base64.b64encode(str(patch).encode()).decode(),
            'patchType': 'JSONPatch',
        }
    })


@app.route('/health', methods=['GET'])
def health():
    return ('', http.HTTPStatus.NO_CONTENT)


@app.errorhandler(HTTPException)
def handle_exception(e):
    """Return JSON instead of HTML for HTTP errors."""
    # start with the correct headers and status code from the error
    response = e.get_response()
    # replace the body with JSON
    response.data = json.dumps({
        'code': e.code,
        'name': e.name,
        'description': e.description,
    })
    response.content_type = 'application/json'
    return response


def main():
    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    logging.info('Started mutating webhook server')

    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    opts = {
        'host': '0.0.0.0',
        'port': 5000
    }

    if os.path.isfile(SSL_CERT_FILE):
        opts.update({
            'port': 443,
            'ssl_context': (
                SSL_CERT_FILE,
                SSL_KEY_FILE
            )
        })

    app.run(**opts)  # pragma: no cover
