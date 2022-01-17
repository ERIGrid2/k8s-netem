from k8s_netem.controller import Controller
from k8s_netem.profile import Profile


class FlexeController(Controller):
    type = 'Flexe'

    def __init__(self, intf: str):
        super().__init__(intf)

    def init(self):
        self.update()

    def deinit(self):
        self.logger.info('deinit')

    def add_profile(self, profile: Profile):
        self.logger.info('Add profile: %s', profile)
        self.logger.info('  with parameters: %s', profile.parameters)

    def remove_profile(self, profile: Profile):
        self.logger.info('Remove profile: %s', profile)

    def update_profile(self, profile: Profile):
        self.logger.info('Update profile: %s', profile)
