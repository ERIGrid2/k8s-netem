from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
import base64
import copy
import os
import os.path
import http
import json
import jsonpatch

from kubernetes import client, config

SSL_CERT_FILE = os.environ.get('SSL_CERT_FILE', '/certs/tls.crt')
SSL_KEY_FILE = os.environ.get('SSL_KEY_FILE', '/certs/tls.key')

api = None
app = Flask(__name__)

def match_pods(pods, selector):
    # A null label selector matches no objects.
    if selector is None:
        return []

    expressions = selector.get('matchExpressions', [])

    # Convert matchLabels into matchExpressions
    for key, value in selector.get('matchLabels', {}).items():
        expressions.append({
            'key': key,
            'values': [value],
            'operator': 'In'
        })

    # An empty label selector matches all objects.
    if len(expressions) == 0:
        return pods

    matched = []
    for pod in pods:
        labels = pod['metadata'].get('labels', {})

        for expr in expressions:
            key = expr.get('key')
            vals = expr.get('values')
            op = expr.get('operator')

            val = labels.get(key)

            match = False
            if op == 'In':
                match = val in vals
            elif op == 'NotIn':
                match = val not in vals
            elif op == 'Exists':
                match = key in labels
            elif op == 'DoesNotExist':
                match = key not in labels

            if match:
                matched.append(pod)

    return matched

def get_profiles():
    ret = api.list_cluster_custom_object(
        group='k8s-netem.riasc.io',
        version='v1',
        plural='trafficprofiles')

    return ret['items']


def match_profiles(pod, profiles):
    matched = []
    for profile in profiles:
        selector = profile['spec']['podSelector']

        if match_pods([pod], selector) != []:
            matched.append(profile)

    return matched

def mutate_pod(pod):
    profiles = get_profiles()

    if len(match_profiles(pod, profiles)) > 0:
        pod['spec']['containers'].append({
            'name': 'k8s-netem',
            'image': 'erigrid2/k8s-netem'
        })

@app.route('/mutate', methods=['POST'])
def mutate():
    print(request.json)
    spec = request.json['request']['object']
    modified_spec = copy.deepcopy(spec)

    mutate_pod(modified_spec)

    patch = jsonpatch.JsonPatch.from_diff(spec, modified_spec)

    return jsonify({
        'response': {
            'allowed': True,
            'uid': request.json['request']['uid'],
            'patch': base64.b64encode(str(patch).encode()).decode(),
            'patchtype': 'JSONPatch',
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
    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    global api
    api = client.CustomObjectsApi()

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

if __name__ == '__main__':
    main()
