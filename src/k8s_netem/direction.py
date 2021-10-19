import logging
import nftables

from k8s_netem.profile import Profile
from k8s_netem.rule import Rule


class Direction:

    def __init__(self, profile: 'Profile', spec: dict, dir: str = 'ingress'):
        self.profile = profile
        self.direction = dir
        self.spec = spec

        self.chain = self.direction

        rules = profile.spec.get(self.direction, [])
        self.rules = [Rule(self, i, r) for i, r in enumerate(rules)]

    def init(self):
        self.init_nftables()

        for rule in self.rules:
            rule.init()

        logging.info('Initialized %s direction of profile %s', self.direction, self.profile)

    def deinit(self):
        self.controller.deinit(self.interface, self.spec)

        for rule in self.rules:
            rule.deinit()

        logging.info('Deinitialized %s direction of profile %s', self.direction, self.profile)

    def init_nftables(self):
        cmds = [
          {
            'add': {
              'chain': {
                **self.profile.table,
                'chain': self.direction
              }
            }
          }
        ]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)
