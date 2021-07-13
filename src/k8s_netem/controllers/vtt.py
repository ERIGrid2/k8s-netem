import subprocess
import tempfile
import json
from typing import List, Dict
from k8s_netem.controller import Controller

class VttController(Controller):

    def __init__(self, ingress: bool, filters: list = []):
        self.ingress = ingress
        self.filters = filters

    def __del__(self):
        self.deinitialize()

    def initialize(self, interface: str, options: dict = {}):
        self.interface = interface
        self.options = options

        self.config = self.generate_config()
        self.config_file = tempfile.NamedTemporaryFile()

        json.dump(self.config, self.config)

        self.proc = subprocess.Popen(['vtt-netem', self.config_file.name])

    def deinitialize(self):
        self.proc.kill()
        self.proc.wait(10)
        self.config_file.close()

    def generate_config(self, options: dict):
        return {
            **options,
            'filter': self.generate_filters()
        }

    def generate_filters(self) -> List[Dict]:
        filters = []

        for filter in self.filters:
            # TODO: Convert to VTT filters
            filters.append({
                'match': {
                    'type': 'CAA=',
                    'src': 'AAAAAAAAAAAAAP//wKjIyw==',
                    'dst': 'AAAAAAAAAAAAAP//wKjI+w==',
                    'proto': 'Bg==',
                    'sport': 'Irg=',
                    'dport': '2Wk='
                },
                'inb': [
                    'enp1s0'
                ],
                'out': [
                    'enp2s0'
                ],
                'dir': False,
                'ingress': '',
                'egress': '',
                'inb_count': 0,
                'inb_lock': True,
                'out_count': 71,
                'out_lock': True
            }

        return filters
