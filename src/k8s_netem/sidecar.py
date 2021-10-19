import os
import sys
import signal
import logging
import nftables

from kubernetes import client, config
from k8s_netem.controller import Controller
from k8s_netem.controllers.script import ScriptController

from k8s_netem.profile import Profile
from k8s_netem.config import DEBUG, POD_NAME, POD_NAMESPACE


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
    ret = v1.list_namespaced_pod(namespace=POD_NAMESPACE,
                                 field_selector=f'metadata.name={POD_NAME}')
    my_pod = ret.items[0]

    intf = get_interface()
    ctrl = ScriptController(intf)

    # Initial list of profiles
    for profile in Profile.list():
        ctrl.add_profile(profile)

    watch(ctrl, my_pod)


def init_nftables():
    cmds = [{
      'flush': {
        'ruleset': None
      }
    }]

    nft = nftables.Nftables()
    rc, output, err = nft.json_cmd(cmds)
    if rc != 0:
        logging.error(output)
        raise RuntimeError('Failed to initialize nftables: %s', err)


def watch(ctrl: Controller, my_pod):
    for event in Profile.watch():
        logging.info('Event: %s', event)

        profile = event['profile']
        type = event['type']

        uid = profile.metadata.uid

        old_profile = ctrl.profiles.get(uid)

        if type in ['ADDED', 'MODIFIED']:
            if old_profile:
                old_profile.update(profile)

            elif profile.match(my_pod):
                profile.init(ctrl)
                ctrl.add_profile(profile)

        elif type == 'DELETED':
            if old_profile:
                old_profile.deinit()
                ctrl.remove_profile(old_profile)
