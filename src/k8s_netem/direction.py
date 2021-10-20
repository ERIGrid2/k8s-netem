from __future__ import annotations
from typing import Dict, TYPE_CHECKING

import logging

from k8s_netem.resource import Resource
from k8s_netem.rule import Rule
from k8s_netem.nftables import nft

if TYPE_CHECKING:
    from k8s_netem.profile import Profile


class Direction(Resource):

    def __init__(self, profile: Profile, spec: Dict, dir: str = 'ingress'):
        super().__init__(spec)

        self.name = f'{profile.name}-{dir}'

        self.logger = logging.getLogger(f'dir:{self.name}')

        self.profile = profile
        self.direction = dir

        self.chain_name = self.direction

        self.rules = {Rule(self, i, r) for i, r in enumerate(self.spec)}

    def init(self):
        self.logger.info('Initializing %s direction of profile %s', self.direction, self.profile)

        self.init_nftables()

        for rule in self.rules:
            rule.init()

    def deinit(self):
        self.logger.info('Deinitializing %s direction of profile %s', self.direction, self.profile)

        for rule in self.rules:
            rule.deinit()

        self.deinit_nftables()

    def cmd_create_chain(self):
        hook = 'input' if self.direction == 'ingress' else 'output'

        return [
          {
            'add': {
              'chain': {
                **self.profile.table,
                'name': self.chain_name,
                'hook': hook,
                'type': 'filter',
                'prio': 0,
              }
            }
          }
        ]

    def cmd_delete_chain(self):
        return [
          {
            'delete': {
              'chain': {
                **self.profile.table,
                'name': self.chain_name
              }
            }
          }
        ]

    def init_nftables(self):
        cmds = []

        cmds += self.cmd_create_chain()

        nft(cmds)

    def deinit_nftables(self):
        cmds = []

        cmds += self.cmd_delete_chain()

        nft(cmds)

    def update(self, new_direction: Direction):
        self.logger.info('Updating direction %s', self)

        # Added rules
        for rule in new_direction.rules - self.rules:
            self.logger.info('Adding rule: %s', rule)

            rule.direction = self
            rule.init()
            self.rules.add(rule)

        # Removed rules
        for rule in self.rules - new_direction.rules:
            self.logger.info('Removing rule: %s', rule)

            rule.deinit()
            self.rules.remove(rule)
