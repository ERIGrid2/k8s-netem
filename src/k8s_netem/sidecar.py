import os
import sys
import signal
import logging
import json

from typing import Dict

from kubernetes import client, config

from k8s_netem.controller import Controller
from k8s_netem.json import CustomEncoder

from k8s_netem.profile import Profile
from k8s_netem.config import POD_NAME, POD_NAMESPACE
from k8s_netem.nftables import nft

# from k8s_netem.controllers.builtin import BuiltinController  # noqa F041
from k8s_netem.controllers.script import ScriptController  # noqa F041
from k8s_netem.controllers.flexe import FlexeController  # noqa F041

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

    ctrls: Dict[str, Controller] = {}

    init_nftables()

    # Initial list of profiles
    for profile in Profile.list():
        if not profile.match(my_pod):
            continue

        try:
            ctrl = ctrls[profile.type]
        except KeyError:
            try:
                ctrl = Controller.from_type(profile.type, intf)
            except RuntimeError as e:
                LOGGER.error('Failed to get controller for profile %s: %s. Ignoring...', profile, e)
                continue

        # Get a unused fwmark
        mark = Controller.get_mark()

        # Initialize nftables to classify traffic with fwmark
        profile.init(mark)

        # Pass new profile to controller
        ctrl.add_profile(profile)

    # Keep watching for added/removed/modified profiles
    watch(ctrls, my_pod, intf)

    ctrl.deinit()


def init_nftables():
    nft([{'flush': {'ruleset': None}}])


def watch(ctrls: Dict[str, Controller], my_pod, intf):
    for event in Profile.watch():
        profile = event['profile']
        type = event['type']
        obj = event['object']

        LOGGER.debug('%s %s %s',
                     type.capitalize(),
                     obj['kind'],
                     obj['metadata']['name'])
        LOGGER.debug('%s', json.dumps(profile, indent=2, cls=CustomEncoder))

        try:
            ctrl = ctrls[profile.type]
        except KeyError:
            try:
                ctrl = Controller.from_type(profile.type, intf)
            except RuntimeError as e:
                LOGGER.error('Failed to get controller for profile %s: %s. Ignoring...', profile, e)
                continue

        old_profile = ctrl.profiles.get(profile.uid)

        if type in ['ADDED', 'MODIFIED']:
            if old_profile:
                params_changed = old_profile.update(profile)

                if params_changed:
                    ctrl.update_profile(old_profile)

            elif profile.match(my_pod):
                mark = ctrl.get_mark()
                profile.init(int(mark))

                ctrl.add_profile(profile)

        elif type == 'DELETED':
            if old_profile:
                old_profile.deinit()

                ctrl.remove_profile(old_profile)

        nft([{'list': {'ruleset': None}}])
