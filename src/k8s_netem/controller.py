from __future__ import annotations
from typing import Dict, TYPE_CHECKING
import itertools
import logging

from k8s_netem.caller import Caller

if TYPE_CHECKING:
    from k8s_netem.profile import Profile

available_mark = itertools.count(1000)


class Controller(Caller):

    def __init__(self, intf: str):
        self.logger = logging.getLogger('controller')

        self.interface: str = intf

        self.profiles: Dict[str, Profile] = {}

    def get_mark(self) -> int:
        return next(available_mark)

    def update(self):
        pass

    def handle_profile(self, profile: Profile):
        uid = profile.uid
        if uid in self.profiles:
            self.update_profile(profile)
        else:
            self.add_profile(profile)

    def add_profile(self, profile: Profile):
        uid = profile.uid
        if uid not in self.profiles:
            self.profiles[uid] = profile
            self.update()
        else:
            raise RuntimeError('Profile already known: name={profile.name}, ns={profile.namespace}, uid={uid}')

    def remove_profile(self, profile: Profile):
        uid = profile.uid
        if uid in self.profiles:
            del self.profiles[uid]
            self.update()
        else:
            raise RuntimeError('Unknown profile: name={profile.name}, ns={profile.namespace}, uid={uid}')

    def update_profile(self, profile: Profile):
        uid = profile.uid
        if uid in self.profiles:
            self.profiles[uid] = profile
            self.update()
        else:
            raise RuntimeError('Unknown profile: name={profile.name}, ns={profile.namespace}, uid={uid}')
