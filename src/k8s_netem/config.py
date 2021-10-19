import os

POD_NAMESPACE = os.environ.get('POD_NAMESPACE')
POD_NAME = os.environ.get('POD_NAME')

DEBUG = 'DEBUG' in os.environ

NFT_TABLE_PREFIX = 'k8s-netem'
