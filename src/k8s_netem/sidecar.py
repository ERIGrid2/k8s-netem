import os
import sys
import signal
import logging

from kubernetes import client, config

from k8s_netem.profile import Profile

POD_NAMESPACE = os.environ.get('POD_NAMESPACE')
POD_NAME = os.environ.get('POD_NAME')

DEBUG = 'DEBUG' in os.environ

def init_signals(netem):
    '''Catch signals in order to stop network impairment before exiting.'''

    # pylint: disable=unused-argument
    def signal_action(signum, frame):
        '''To be executed upon exit signal.'''
        netem.teardown()
        sys.exit(5)

    # Catch SIGINT and SIGTERM so that we can clean up
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, signal_action)

def get_interface():
    """ Find suitable interface """

    intfs = os.listdir('/sys/class/net')

    return [intf for intf in intfs if intf != 'lo'][0]

def main():
    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    logging.info('Started netem sidecar')

    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    # Get my own pod resource
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace=POD_NAMESPACE, field_selector=f'metadata.name={POD_NAME}')
    my_pod = ret.items[0]

    intf = get_interface()

    for event in Profile.watch(my_pod, intf):
        logging.info('Event: %s, profile=%s', event[0], event[1])
