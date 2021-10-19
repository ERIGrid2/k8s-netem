import logging
import threading
import nftables
import json
from typing import List
from kubernetes import watch, client

from k8s_netem.direction import Direction
from k8s_netem.match import LabelSelector
from k8s_netem.config import NFT_BASE


class Rule:

    def __init__(self, direction: 'Direction', index: int, spec):
        self.direction: 'Direction' = direction
        self.index: int = index
        self.spec: dict = spec

        self.threads: List[threading.Thread] = []

        self.set_nets = f'{self.direction.direction}-{self.index}-nets'
        self.set_ports = f'{self.direction.direction}-{self.index}-ports'

    def __hash__(self):
        return hash(json.dumps(self.spec, sort_keys=True))

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def init(self):
        self.init_nftables()

        logging.info('Initialized rule: %s', self.spec)

    def deinit(self):
        for thread in self.threads:
            thread.join(0.0)

    def init_nftables(self):
        cmds = [
          {
            'add': {
              'set': {
                **self.direction.profile.base,
                'name': self.set_nets,
                'type': 'ipv4_addr'
              }
            }
          },
          {
            'add': {
              'set': {
                **self.direction.profile.base,
                'name': self.set_ports,
                'type': ['inet_proto', 'inet_service']
              }
            }
          }
        ]

        # Populate sets

        peers = self.spec.get('from' if self.direction.direction == 'ingress'
                              else 'to')
        if peers:
            for p in peers:
                if 'ipBlock' in p:
                    cmds += [{
                      'add': {
                        {
                          'element': {
                            **self.direction.profile.base,
                            'name': self.set_nets,
                            'elem': p['ipBlock']['cidr']
                          }
                        }
                      }
                    }]

                elif 'namespaceSelector' in p or 'podSelector' in p:
                    thread = threading.Thread(target=self.sync, args=(p,))
                    thread.start()

                    self.threads.append(thread)

        ports = self.spec.get('ports')
        if ports:
            for p in ports:
                port = p.get('port')
                proto = p.get('protocol', 'TCP').lower()

                cmds += [{
                  'add': {
                    {
                      'element': {
                        **self.direction.profile.base,
                        'name': self.set_nets,
                        'elem': [
                            proto,
                            port
                        ]
                      }
                    }
                  }
                }]

        # Add rule
        cmds += [{
          'add': {
            'rule': {
              **NFT_BASE,
              'comment': str(self.index),
              'chain': self.direction.chain,
              'expr': [
                {
                  'match': {
                    'left': {
                      'payload': {
                        'protocol': 'ip',
                        'field': 'dst'
                      }
                    },
                    'right': f'@{self.set_nets}',
                    'op': '=='
                  }
                },
                {
                  'match': {
                    'left': {
                        'meta': {
                            'key': 'l4proto'
                        }
                    },
                    'right': {
                        'set': ['udp', 'tcp']
                    }
                  }
                },
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
                    'right': f'@{self.set_ports}',
                    'op': '=='
                  }
                },
                {
                  'mangle': {
                    'key': {
                      'meta': {
                        'key': 'mark'
                      }
                    },
                    'value': {
                      self.direction.profile.mark
                    }
                  }
                }
              ]
            }
          }
        }]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)

    def deinit_nftables(self):
        cmds = [
          {
            'delete': {
                'set': {
                    **self.direction.profile.base,
                    'name': self.set_nets
                }
            }
          },
          {
            'delete': {
                'set': {
                    **self.direction.profile.base,
                    'name': self.set_ports
                }
            }
          }
        ]

        handle = self.find_handle()
        if handle:
            cmds += [
              {
                'delete': {
                  'rule': {
                    **self.direction.profile.base,
                    'handle': handle
                  }
                }
              }
            ]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)

    def find_handle(self):
        """ Find rule handle in chain by using the nftables comment """

        cmds = [
          {
            'list': {
                'chain': {
                    **self.direction.profile.base,
                    'chain': self.direction.chain
                }
            }
          }
        ]

        nft = nftables.Nftables()
        rc, output, err = nft.json_cmd(cmds)
        if rc != 0:
            logging.error(output)
            raise RuntimeError('Failed to initialize nftables: %s', err)

        elms = output.get('nftables', [])
        for elm in elms:
            rule = elm.get('rule')
            if rule is None:
                continue

            handle = rule.get('handle')
            if handle is None:
                continue

            comment = rule.get('comment')
            if comment == str(self.index):
                return handle

        return None

    def sync(self, peer):
        logging.info('Started sync thread for %s', peer)

        # We only support podSelectors for now...
        if 'podSelector' not in peer:
            raise NotImplementedError()

        w = watch.Watch()
        v1 = client.CoreV1Api()

        selector = LabelSelector(peer['podSelector']).to_labelselector()

        for event in w.stream(v1.list_pod_for_all_namespaces,
                              label_selector=selector):
            pod = event['object']

            logging.info('%s %s/%s (%s)', event['type'].capitalize(),
                         pod.metadata.namespace,
                         pod.metadata.name,
                         pod.status.pod_ip)

            nft = nftables.Nftables()
            cmds = []

            type = event['type']
            if type in ['MODIFIED', 'ADDED', 'DELETED']:
                if pod.status.pod_ip is not None:
                    op = 'delete' if type == 'DELETED' else 'add'
                    cmds += [{
                      op: {
                        'element': {
                          **self.base,
                          'name': self.set_nets,
                          'elem': pod.status.pod_ip
                        }
                      }
                    }]

            nft = nftables.Nftables()
            rc, output, err = nft.json_cmd(cmds)
            if rc != 0:
                logging.error(output)
                raise RuntimeError('Failed to initialize nftables: %s', err)
