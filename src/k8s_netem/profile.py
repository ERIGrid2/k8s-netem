import logging
import nftables
from typing import Dict
from kubernetes import client, watch

from k8s_netem.match import LabelSelector
from k8s_netem.direction import Direction
from k8s_netem.controller import Controller
from k8s_netem.config import NFT_TABLE_PREFIX


class Profile:

    def __init__(self, ctrl: Controller, obj: dict):

        self.name: str = obj['metadata']['name']
        self.namespace: str = obj['metadata']['namespace']
        self.uid: str = obj['metadata']['uid']
        self.spec: Dict = obj['spec']
        self.type: str = self.spec.get('type', 'Builtin')
        self.parameters: Dict = self.spec.get('parameters', {})

        self.table = {
            'family': 'ip',
            'table': NFT_TABLE_PREFIX
        }

        if 'ingress' in self.spec:
            self.ingress = Direction(self, self.spec['ingress'], 'ingress')

        if 'egress' in self.spec:
            self.egress = Direction(self, self.spec['egress'], 'egress')

    def __str__(self):
        return f'{self.namespace}/{self.name} ({self.type})<{self.uid}>'

    def init(self, ctrl: Controller):
        self.controller = ctrl
        self.mark = ctrl.get_mark()

        self.init_nftables()

        if self.ingress:
            self.ingress.init()

        if self.egress:
            self.egress.init()

        logging.info('Initialized profile %s', self.name)

    def deinit(self):
        if self.ingress:
            self.ingress.deinit()

        if self.egress:
            self.egress.deinit()

        logging.info('Deinitialized profile %s', self.name)

    def init_nftables(self):
        cmds = [
          {
            'add': {
              'table': {
                'family': 'ip',
                'name': f'{NFT_TABLE_PREFIX}-{self.name}'
              }
            }
          }
        ]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)

    def deinit_nftables(self):
        cmds = [
          {
            'delete': {
              'table': {
                'family': 'ip',
                'name': f'{NFT_TABLE_PREFIX}-{self.name}'
              }
            }
          }
        ]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)

    def match(self, pod):
        selector = LabelSelector(self.spec['podSelector'])

        return selector.match(pod.metadata.labels)

    def update(self, newp):
        # TODO: implement

        logging.info('Updating profile %s', self.name)

    @classmethod
    def list(cls):
        api = client.CustomObjectsApi()

        ret = api.list_cluster_custom_object(
                group='k8s-netem.riasc.eu',
                version='v1',
                plural='trafficprofiles')

        return map(cls, ret['items'])

    @classmethod
    def watch(cls):
        api = client.CustomObjectsApi()
        w = watch.Watch()

        for event in w.stream(api.list_cluster_custom_object,
                              group='k8s-netem.riasc.eu',
                              version='v1',
                              plural='trafficprofiles'):

            obj = event['object']

            event['profile'] = cls(obj)

            yield event
