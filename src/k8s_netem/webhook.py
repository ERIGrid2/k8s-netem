from flask import Flask, jsonify, request
import base64
import copy
import http
import jsonpatch

ANNOTATION_PREFIX = 'k8s-netem.riasc.io'

app = Flask(__name__)

@app.route('/mutate', methods=['POST'])
def mutate():
    spec = request.json['request']['object']
    modified_spec = copy.deepcopy(spec)

    try:
        modified_spec['spec']['containers'].append({
            'name': 'netem-sidecar',
            'image': 'erigrid2/k8s-netem',
            'env': [
                {
                    'name': 'PROFILE',
                    'value': spec['meta']['annotations'][ANNOTATION_PREFIX + '/profile']
                }
            ]
        })
    except KeyError:
        pass

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)  # pragma: no cover
