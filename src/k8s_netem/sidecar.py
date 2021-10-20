import os
import sys
import signal
import logging
import json

from kubernetes import client, config

from k8s_netem.controller import Controller
from k8s_netem.controllers.script import ScriptController
from k8s_netem.json import CustomEncoder

from k8s_netem.profile import Profile
from k8s_netem.config import POD_NAME, POD_NAMESPACE
from k8s_netem.nftables import nft

import k8s_netem.log as log

LOGGER = logging.getLogger('sidecard')


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
    log.setup()

    LOGGER.info('Started netem sidecar')

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

    ctrl.init()

    init_nftables()

    # Initial list of profiles
    for profile in Profile.list():
        if profile.match(my_pod):
            mark = ctrl.get_mark()
            profile.init(mark)
            ctrl.add_profile(profile)

    watch(ctrl, my_pod)

    ctrl.deinit()


def init_nftables():
    cmds = [
        {
            'flush': {
                'ruleset': None
            }
        }
    ]

    nft(cmds)


def watch(ctrl: Controller, my_pod):
    for event in Profile.watch():
        profile = event['profile']
        type = event['type']
        obj = event['object']

        LOGGER.debug('%s %s %s',
                     type.capitalize(),
                     obj['kind'],
                     obj['metadata']['name'])
        LOGGER.trace('%s', json.dumps(profile, indent=2, cls=CustomEncoder))

        uid = profile.uid

        old_profile = ctrl.profiles.get(uid)

        if type in ['ADDED', 'MODIFIED']:
            if old_profile:
                params_changed = old_profile.update(profile)

                if params_changed:
                    ctrl.update()

            elif profile.match(my_pod):
                mark = ctrl.get_mark()
                profile.init(int(mark))

                ctrl.add_profile(profile)

        elif type == 'DELETED':
            if old_profile:
                old_profile.deinit()

                ctrl.remove_profile(old_profile)

        nft([{'list': {'ruleset': None}}])
