from __future__ import annotations
from typing import Dict, Set, Any, TYPE_CHECKING

import logging
import ipaddress
import random

from k8s_netem.resource import Resource
from k8s_netem.nftables import nft
from k8s_netem.peer import Peer

if TYPE_CHECKING:
    from k8s_netem.direction import Direction


class Rule(Resource):

    def __init__(self, dir: Direction, index: int, spec: Dict):
        super().__init__(spec)

        self.logger = logging.getLogger(f'rule:{dir.name}-{index}')

        self.direction = dir
        self.index = index

        self.generation = random.randint(0, 1 << 16)
        self.name = f'{self.direction.direction}-{self.index}-{self.generation}'
        self.set_ports_name = f'{self.name}-ports'
        self.set_nets_name = f'{self.name}-nets'
        self.set_ether_types_name = f'{self.name}-ether-types'
        self.set_inet_protos_name = f'{self.name}-inet-protos'

        peer_specs = spec.get('from' if self.direction.direction == 'ingress' else 'to', [])

        self.peers = [Peer(self, i, p) for i, p in enumerate(peer_specs)]
        self.ports = self.spec.get('ports', [])
        self.ether_types = self.spec.get('etherTypes', [])
        self.inet_protos = self.spec.get('inetProtos', [])

        self.nets: Set[ipaddress.IPv4Network] = set()

    def init(self):
        self.logger.info('Initializing rule %d of %s of %s', self.index, self.direction, self.direction.profile)

        self.init_nftables()

        # Start synchronization threads
        for peer in self.peers:
            peer.init()

    def deinit(self):
        self.logger.info('Deinitializing rule %d of %s of %s', self.index, self.direction, self.direction.profile)

        for peer in self.peers:
            peer.deinit()

        self.deinit_nftables()

    def cmd_create_sets(self):
        return [
          {
            'add': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_nets_name,
                'type': 'ipv4_addr',
                'flags': ['interval']
              }
            }
          },
          {
            'add': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_ports_name,
                'type': ['inet_proto', 'inet_service']
              }
            }
          },
          {
            'add': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_ether_types_name,
                'type': 'ether_type'
              }
            }
          },
          {
            'add': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_inet_protos_name,
                'type': 'inet_proto'
              }
            }
          }
        ]

    def cmd_populate_set_ether_types(self):
        cmds = []

        for ether_type in self.ether_types:
            cmds += self.cmd_modify_set_ether_type('add', ether_type)

        return cmds

    def cmd_populate_set_inet_protos(self):
        cmds = []

        for inet_protos in self.inet_protos:
            cmds += self.cmd_modify_set_inet_proto('add', inet_protos)

        return cmds

    def cmd_populate_set_nets(self):
        cmds = []

        for peer in self.peers:
            ip_block = peer.spec.get('ipBlock')

            if ip_block is not None:
                cidr = ip_block.get('cidr')
                cidr = ipaddress.IPv4Network(cidr)

                self.nets.add(cidr)

                cmds += self.cmd_modify_set_net('add', cidr)

        for proto in self.inet_protos:
            cmds += self.cmd_modify_set_port

        for type in self.ether_types:
            pass

        return cmds

    def cmd_populate_set_ports(self):
        cmds = []

        for port in self.ports:
            port_no = port.get('port')
            protocol = port.get('protocol', 'TCP').lower()

            cmds += self.cmd_modify_set_port('add', protocol, port_no)

        return cmds

    def cmd_create_rule(self):
        exprs = []

        if len(self.ether_types) > 0:
            exprs += [
              {
                'match': {
                  'left': {
                    'meta': {
                        'key': 'protocol'
                    }
                  },
                  'right': f'@{self.set_ether_types_name}',
                  'op': '=='
                }
              }
            ]

        if len(self.inet_protos) > 0:
            exprs += [
              {
                'match': {
                  'left': {
                    'meta': {
                        'key': 'l4proto'
                    }
                  },
                  'right': f'@{self.set_inet_protos_name}',
                  'op': '=='
                }
              }
            ]

        # If at least one peer is provided in the spec,
        # we will match against the associated networks
        # even if the selectors are not matching any pods
        if len(self.peers) > 0:
            exprs += [
              {
                'match': {
                  'left': {
                    'payload': {
                      'protocol': 'ip',
                      'field': 'daddr'
                    }
                  },
                  'right': f'@{self.set_nets_name}',
                  'op': '=='
                }
              }
            ]

        if len(self.ports):
            exprs += [
              {
                'match': {
                  'left': {
                    'concat': [
                      {
                        'meta': {
                            'key': 'l4proto'
                        }
                      },
                      {
                        # Match both UDP and TCP ports here
                        'payload': {
                            'protocol': 'th',
                            'field': 'dport'
                        }
                      }
                    ]
                  },
                  'right': f'@{self.set_ports_name}',
                  'op': '=='
                }
              }
            ]

        exprs += [
          {
            'mangle': {
              'key': {
                'meta': {
                  'key': 'mark'
                }
              },
              'value': self.direction.profile.mark
            }
          }
        ]

        return [
          {
            'add': {
              'rule': {
                **self.direction.profile.table,
                'comment': self.name,
                'chain': self.direction.chain_name,
                'expr': exprs
              }
            }
          }
        ]

    def cmd_delete_sets(self):
        return [
          {
            'delete': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_ether_types_name
              }
            }
          },
          {
            'delete': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_inet_protos_name
              }
            }
          },
          {
            'delete': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_nets_name
              }
            }
          },
          {
            'delete': {
              'set': {
                **self.direction.profile.table,
                'name': self.set_ports_name
              }
            }
          }
        ]

    def cmd_delete_rule(self):
        handle = self.find_handle(self.name)
        if handle is None:
            raise RuntimeError(f'Failed to find rule by comment: {self.name}')

        return [
          {
            'delete': {
              'rule': {
                **self.direction.profile.table,
                'chain': self.direction.chain_name,
                'handle': handle
              }
            }
          }
        ]

    def cmd_update_rule(self):
        return self.rule.cmd_delete_rule() + \
               self.rule.cmd_create_rule()

    def cmd_modify_set_ether_type(self, op: str, ether_type: str | int, comment: str = None):
        elem = {
          'val': ether_type
        }

        if comment is not None:
            elem['comment'] = comment

        return [
          {
            op: {
              'element': {
                **self.direction.profile.table,
                'name': self.set_ether_types_name,
                'elem': [
                  elem
                ]
              }
            }
          }
        ]

    def cmd_modify_set_inet_proto(self, op: str, protocol: str | int, comment: str = None):
        elem = {
          'val': protocol
        }

        if comment is not None:
            elem['comment'] = comment

        return [
          {
            op: {
              'element': {
                **self.direction.profile.table,
                'name': self.set_inet_protos_name,
                'elem': [
                  elem
                ]
              }
            }
          }
        ]

    def cmd_modify_set_port(self, op: str, protocol: str, port: str | int, comment: str = None):
        elem: Dict[str, Any] = {
          'concat': [
            protocol,
            int(port)
          ]
        }

        if comment is not None:
            elem['comment'] = comment

        return [
          {
            op: {
              'element': {
                **self.direction.profile.table,
                'name': self.set_ports_name,
                'elem': [
                  elem
                ]
              }
            }
          }
        ]

    def cmd_modify_set_net(self, op: str, cidr: ipaddress.IPv4Network, comment: str = None):
        if cidr.prefixlen >= ipaddress.IPV4LENGTH:  # IPv6
            val = str(cidr.network_address)
        else:
            val = {
              'prefix': {
                'addr': str(cidr.network_address),
                'len': cidr.prefixlen
              }
            }

        elem = {
            'val': val
        }

        if comment is not None:
            elem['comment'] = comment

        return [
          {
            op: {
              'element': {
                **self.direction.profile.table,
                'name': self.set_nets_name,
                'elem': [
                  {
                    'elem': elem
                  }
                ]
              }
            }
          }
        ]

    def init_nftables(self):
        cmds = []

        cmds += self.cmd_create_sets()
        cmds += self.cmd_populate_set_ether_types()
        cmds += self.cmd_populate_set_inet_protos()
        cmds += self.cmd_populate_set_nets()
        cmds += self.cmd_populate_set_ports()
        cmds += self.cmd_create_rule()

        nft(cmds)

    def deinit_nftables(self):
        cmds = []

        cmds += self.cmd_delete_rule()
        cmds += self.cmd_delete_sets()

        nft(cmds)

    def find_handle(self, comment):
        """ Find rule handle in chain by using the nftables comment """

        cmds = [
          {
            'list': {
                'chain': {
                    **self.direction.profile.table,
                    'name': self.direction.chain_name
                }
            }
          }
        ]

        output = nft(cmds)

        elms = output.get('nftables', [])
        for elm in elms:
            rule = elm.get('rule')
            if rule is None:
                continue

            handle = rule.get('handle')
            if handle is None:
                continue

            cmt = rule.get('comment')
            if cmt == comment:
                return handle

        return None

    def add_net(self, cidr: ipaddress.IPv4Network, comment: str = None):
        if cidr not in self.nets:
            nft(self.cmd_modify_set_net('add', cidr, comment))
            self.nets.add(cidr)

    def delete_net(self, cidr: ipaddress.IPv4Network):
        if cidr in self.nets:
            nft(self.cmd_modify_set_net('delete', cidr))
            self.nets.remove(cidr)
