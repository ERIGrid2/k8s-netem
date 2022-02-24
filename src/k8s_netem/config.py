import os

POD_NAMESPACE = os.environ.get('POD_NAMESPACE')
POD_NAME = os.environ.get('POD_NAME')

SSL_CERT_FILE = os.environ.get('SSL_CERT_FILE', '/certs/tls.crt')
SSL_KEY_FILE = os.environ.get('SSL_KEY_FILE', '/certs/tls.key')

INJECT_TO_ALL = os.environ.get('INJECT_TO_ALL') in ['1', 'true', 'on']

DEBUG = os.environ.get('DEBUG') in ['1', 'true', 'on']

NFT_TABLE_PREFIX = 'k8s-netem'
