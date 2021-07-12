import os
import sys
import signal
import logging

from kubernetes import client, config

from k8s_netem.impairment import Impairement

PROFILE = os.environ.get('PROFILE') # Set by mutating admission webhook
NAMESPACE = os.environ.get('NAMESPACE') # Set by downward API

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

def main():
    logging.basicConfig(level=logging.INFO)

    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    api = client.CustomObjectsApi()

    # Fetch profile CRD
    profile = api.get_cluster_custom_object(
        group='k8s-netem.riasc.io',
        version='v1',
        namespce=NAMESPACE,
        plural='trafficprofiles',
        name=PROFILE)

    # Find suitable interface
    intfs = os.listdir('/sys/class/net')
    intf = [intf for intf in intfs if intf != 'lo'][0]

    imp = Impairement(intf, profile['include'], profile['exclude'])
    imp.initialize()

    if 'netem' in imp:
        imp.netem(**imp['netem'])

    if 'rate' in imp:
        imp.rate(**imp['rate'])

    imp.run()
