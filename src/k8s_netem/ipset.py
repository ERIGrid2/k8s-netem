import subprocess
import shlex

class IPset:

    def __init__(self, name, method, datatype):
        self.name = name
        self.method = method
        self.datatype = datatype

        self.create()

    def __del__(self):

        self.destroy()

    def add(self, ipaddr):
        self._check_call(f'ipset add -exist {self.name} {ipaddr}')

    def delete(self, ipaddr):
        self._check_call(f'ipset del {self.name} {ipaddr}')

    def create(self):
        create_flags = ''
        if self.method == 'bitmap' and self.datatype == 'port':
            create_flags += ' range 0-65535'

        self._check_call(f'ipset create -exist {self.name} {self.method}:{self.datatype}{create_flags}')
        self._check_call(f'ipset flush {self.name}')

    def destroy(self):
        self._check_call(f'ipset destroy {self.name}')

    @classmethod
    def _call(cls, command):
        """Run command."""
        subprocess.call(shlex.split(command))

    @classmethod
    def _check_call(cls, command):
        """Run command, raising CalledProcessError if it fails."""
        subprocess.check_call(shlex.split(command))
