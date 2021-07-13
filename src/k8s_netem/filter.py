from typing import List

from k8s_netem.ipset import IPset

class Filter:

    def __init__(self):
        self.family = 'ip'

    def __str__(self):
        raise NotImplementedError()

class IPsetFilter(Filter):

    def __init__(self, ipset: IPset, ingress: bool = False):
        super().__init__()

        self.ipset = ipset
        self.flags = 'src' if ingress else 'dst'

    def __str__(self):
        return f'ipset({self.ipset.name} {self.flags})'

class MultiIPsetFilter(Filter):

    def __init__(self, ipsets: List[IPset], ingress: bool = False, op: str = 'and'):
        super().__init__()
    
        self.ipsets = ipsets
        self.ingress = ingress
        self.op = op

    def __str__(self):
        exprs = [IPsetFilter(ipset, self.ingress) for ipset in self.ipsets]
        
        return '(' + f' {self.op} '.join(map(str, exprs)) + ')'
