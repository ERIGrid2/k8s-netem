import os
import sys
import signal
import logging
import time

from kubernetes import client, config, watch

from k8s_netem.profile import Profile

POD_NAMESPACE = os.environ.get('POD_NAMESPACE')
POD_NAME = os.environ.get('POD_NAME')

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
    logging.basicConfig(level=logging.INFO)

    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    v1 = client.CoreV1Api()
    api = client.CustomObjectsApi()

    # Get my own resource
    ret = v1.list_namespaced_pod(namespace=POD_NAMESPACE, field_selector=f'metadata.name={POD_NAME}')
    my_pod = ret.items[0]

    intf = get_interface()

    Profile.watch(my_pod, intf)

if __name__ == '__main__':
    main()
