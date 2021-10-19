import subprocess
import tempfile
import json
from typing import List, Dict
from k8s_netem.controller import Controller

EXECUTABLE = 'tc-script'


class ScriptController(Controller):

    def __init__(self, intf: str, options: Dict = {}):
        super().__init__(intf)

        self.config_file = tempfile.NamedTemporaryFile()
        self.options = options

        self.type = 'Script'

    def __del__(self):
        self.config_file.close()
        self.deinit()

    def init(self):
        self.update()

        self.proc = subprocess.Popen([EXECUTABLE, self.config_file.name])

    def update(self):
        json.dump(self.config, self.config_file)

    def deinit(self):
        self.proc.kill()
        self.proc.wait(10)
        self.config_file.close()

    @property
    def config(self) -> Dict:
        return {
            **self.options,
            'interface': self.interface,
            'flows': self.flows
        }

    @property
    def flows(self) -> List[Dict]:
        flows = []

        for _, profile in self.profiles.items():
            flows.append(
                {
                    'metadata': profile.spec.get('metadata'),
                    'filter': {
                        'fwmark': profile.mark
                    },
                    'parameters': profile.parameters
                }
            )

        return flows
