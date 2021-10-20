from typing import Dict
import json


def hash_dict(d: Dict):
    return hash(json.dumps(d, sort_keys=True))


def compare_dicts(a: Dict, b: Dict):
    return hash_dict(a) == hash_dict(b)


class Resource:

    def __init__(self, spec: Dict):
        self.spec = spec

    def __hash__(self):
        return hash_dict(self.spec)

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()
