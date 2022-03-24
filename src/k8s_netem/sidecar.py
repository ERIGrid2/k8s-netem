import os
import sys
import signal
import logging
import json

from typing import Dict

from kubernetes import client, config
from kubernetes.config.incluster_config import InClusterConfigLoader, SERVICE_CERT_FILENAME

from k8s_netem.controller import Controller
from k8s_netem.json import CustomEncoder

from k8s_netem.profile import Profile
from k8s_netem.config import POD_NAME, POD_NAMESPACE
from k8s_netem.nftables import nft

from k8s_netem.controllers.builtin import BuiltinController  # noqa F041
from k8s_netem.controllers.script import ScriptController  # noqa F041
from k8s_netem.controllers.flexe import FlexeController  # noqa F041

import k8s_netem.log as log

LOGGER = logging.getLogger('sidecard')


def dump_nftables():
    rulset = nft([
        {
            'list': {
                'ruleset': None
            }
        }
    ])
    LOGGER.debug(rulset)


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


def load_incluster_config_with_token(token: str):
    token_filename = '/tmp/token'
    with open(token_filename, 'w') as token_file:
        token_file.write(token)

    loader = InClusterConfigLoader(
        token_filename=token_filename,
        cert_filename=SERVICE_CERT_FILENAME)
    loader.load_and_set()


def main():
    log.setup()

    LOGGER.info('Started netem sidecar')

    if os.environ.get('KUBECONFIG'):
        config.load_kube_config()
    elif os.environ.get('KUBETOKEN'):
        token = os.environ.get('KUBETOKEN')

        load_incluster_config_with_token(token)
    else:
        config.load_incluster_config()

    # Get my own pod resource
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace=POD_NAMESPACE,
                                 field_selector=f'metadata.name={POD_NAME}')
    my_pod = ret.items[0]

    # InterfaceName -> Controller
    interfaces: Dict[str, Controller] = {}

    init_nftables()

    # Initial list of profiles
    for profile in Profile.list():
        if not profile.match(my_pod):
            continue

        if profile.interface is None:
            LOGGER.error('Failed to identify network interface')
            continue

        if profile.interface in interfaces:
            ctrl = interfaces[profile.interface]
            if ctrl.type != profile.type:
                LOGGER.error('Conflicing controllers')
                continue

            LOGGER.info('Using existing %s controller for profile %s', profile.type, profile)
        else:
            try:
                LOGGER.info('Creating new %s controller for profile %s', profile.type, profile)
                ctrl = Controller.from_type(profile.type, profile.interface)
                interfaces[profile.interface] = ctrl
            except RuntimeError as e:
                LOGGER.error('Failed to get controller for profile %s: %s. Ignoring...', profile, e)
                continue

        # Get a unused fwmark
        mark = Controller.get_mark()

        # Initialize nftables to classify traffic with fwmark
        profile.init(mark)

        # Pass new profile to controller
        ctrl.add_profile(profile)

    # Show current nftables rulset
    dump_nftables()

    # Keep watching for added/removed/modified profiles
    watch(interfaces, my_pod)

    ctrl.deinit()


def init_nftables():
    nft([{'flush': {'ruleset': None}}])


def watch(interfaces: Dict[str, Controller], my_pod):
    for event in Profile.watch():
        profile = event['profile']
        type = event['type']
        obj = event['object']

        LOGGER.debug('%s %s %s',
                     type.capitalize(),
                     obj['kind'],
                     obj['metadata']['name'])
        LOGGER.debug('%s', json.dumps(profile, indent=2, cls=CustomEncoder))

        if profile.interface is None:
            LOGGER.error('Failed to identify network interface')
            continue

        if profile.interface in interfaces:
            ctrl = interfaces[profile.interface]
            LOGGER.info('Using existing %s controller for profile %s', profile.type, profile)
        else:
            try:
                LOGGER.info('Creating new %s controller for profile %s', profile.type, profile)
                ctrl = Controller.from_type(profile.type, profile.interface)
                interfaces[profile.interface] = ctrl
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

                # Deinitialize and remove controller once the last
                # Profile has been removed. This allows new Profiles
                # with a different type to target this interface.
                if len(ctrl.profiles) == 0:
                    LOGGER.info("Removing controller %s from interface %s", ctrl, profile.interface)
                    ctrl.deinit()
                    del interfaces[profile.interface]

        # Show current nftables rulset
        dump_nftables()
