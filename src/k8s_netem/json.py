import json

from k8s_netem.profile import Profile


class CustomEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Profile):
            return o.ressource

        return json.JSONEncoder.default(self, o)
