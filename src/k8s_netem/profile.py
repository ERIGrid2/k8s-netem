from __future__ import annotations
from typing import Dict, Iterable

import logging
from kubernetes import client, watch

from k8s_netem.resource import Resource, compare_dicts
from k8s_netem.match import LabelSelector
from k8s_netem.direction import Direction
from k8s_netem.config import NFT_TABLE_PREFIX
from k8s_netem.nftables import nft

DIRECTIONS = ['ingress', 'egress']


class Profile(Resource):

    def __init__(self, res: Dict):
        spec = res.get('spec', {})

        super().__init__(spec)

        self.ressource = res

        self.meta = res.get('metadata', {})

        self.name: str = self.meta.get('name')
        self.uid: str = self.meta.get('uid')

        self.type = self.spec.get('type', 'Builtin')
        self.parameters = self.spec.get('parameters', {})

        self.logger = logging.getLogger(f'profile:{self.name}')

        self.table_name = f'{NFT_TABLE_PREFIX}-{self.name}'

        self.table = {
            'family': 'ip',
            'table': self.table_name
        }

        self.ingress = None
        self.egress = None

        if 'ingress' in self.spec:
            self.ingress = Direction(self, self.spec['ingress'], 'ingress')
        if 'egress' in self.spec:
            self.egress = Direction(self, self.spec['egress'], 'egress')

        # Remove some unneded info
        try:
            del self.meta['managedFields']
            del self.meta['annotations']['kubectl.kubernetes.io/last-applied-configuration']
        except KeyError:
            pass

    def __str__(self):
        return f'{self.name} ({self.type})<{self.uid}>'

    def init(self, mark: int):
        self.logger.info('Initializing profile %s', self.name)

        self.mark = mark

        self.init_nftables()

        if self.ingress:
            self.ingress.init()
        if self.egress:
            self.egress.init()

    def deinit(self):
        self.logger.info('Deinitializing profile %s', self.name)

        if self.ingress:
            self.ingress.deinit()
        if self.egress:
            self.egress.deinit()

    def init_nftables(self):
        cmds = [
          {
            'add': {
              'table': {
                'family': 'ip',
                'name': self.table_name
              }
            }
          }
        ]

        nft(cmds)

    def deinit_nftables(self):
        cmds = [
          {
            'delete': {
              'table': {
                'family': 'ip',
                'name': self.table_name
              }
            }
          }
        ]

        nft(cmds)

    def match(self, pod):
        selector = LabelSelector(self.spec['podSelector'])

        return selector.match(pod.metadata.labels)

    def update(self, new_profile: Profile):
        self.logger.info('Updating profile %s', self.name)

        if self == new_profile:
            self.logger.info('Profile %s has not changed', self.name)
            return

        if self.type != new_profile.type:
            raise RuntimeError('Changing a profile type is not supported')

        for d in DIRECTIONS:
            direction = getattr(self, d)
            new_direction = getattr(new_profile, d)

            # Direction is updated
            if direction and new_direction:
                direction.update(new_direction)

            # Direction has been removed
            elif direction and not new_direction:
                direction = getattr(self, d)

                direction.deinit()

                setattr(self, d, None)

            # Direction has been added
            elif not direction and new_direction:
                new_direction = getattr(new_profile, d)

                new_direction.profile = self
                new_direction.init()

                setattr(self, d, new_direction)

        if compare_dicts(self.parameters, new_profile.parameters):
            self.logger.info('Profile parameters of %s have not changed', self.name)

            return False
        else:
            self.parameters = new_profile.parameters

            return True

    @classmethod
    def list(cls) -> Iterable[Profile]:
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
