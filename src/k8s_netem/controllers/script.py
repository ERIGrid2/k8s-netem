import subprocess
import tempfile
import json
from typing import List, Dict
from k8s_netem.controller import Controller

EXECUTABLE = 'tc-script'


class ScriptController(Controller):

    def __init__(self, intf: str, options: Dict = {}):
        super().__init__(intf)

        self.config_file = tempfile.NamedTemporaryFile('w+')
        self.options = options

        self.type = 'Script'
        self.proc = None

    def __del__(self):
        self.config_file.close()
        self.deinit()

    def init(self):
        self.update()

        self.proc = subprocess.Popen([EXECUTABLE, self.config_file.name])

    def update(self):
        self.config_file.seek(0)
        self.config_file.truncate(0)
        json.dump(self.config, self.config_file)
        self.config_file.flush()

    def deinit(self):
        if self.proc is not None:
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
                    'metadata': profile.meta,
                    'filter': {
                        'fwmark': profile.mark
                    },
                    'parameters': profile.parameters
                }
            )

        return flows
