from typing import Dict, Set

from k8s_netem.controller import Controller
from k8s_netem.profile import Profile


class BuiltinController(Controller):
    """Wrapper around netem module and tc commands."""

    type = 'Builtin'

    def __init__(self, intf: str, options: Dict = {}):
        super().__init__(intf)

        self.options = options

        self.prio_bands = 0  # qdisc does not exist yet
        self.prio_bands_avail: Set[int] = set()

        # We initially reserve 8 bands for profiles
        self._setup_prio(initial=True, bands_extra=8)

    def deinit(self):
        self._call(f'tc qdisc delete dev {self.interface} root')

        self._dump_tc()

    def _dump_tc(self):
        self._call(f'tc qdisc show dev {self.interface}')
        self._call(f'tc filter show dev {self.interface}')
        self._call(f'tc -g class show dev {self.interface}')

    def _setup_prio(self, initial=False, bands_extra=1):
        if initial:
            operation = 'add'
        else:
            operation = 'change'

        self.prio_bands += bands_extra

        if initial:
            self.logger.info(f'Performing initial setup of prio qdisc with {self.prio_bands+3} bands')

            self._call(f'tc qdisc delete dev {self.interface} root')

        else:
            self.logger.info(f'Performing update of prio qdisc with {self.prio_bands+3} bands')

        self._check_call(f'tc qdisc {operation} dev {self.interface} root handle 1: prio bands {self.prio_bands+3}')

        self.prio_bands_avail.update(range(3, 3+self.prio_bands))

        self._dump_tc()

    # pylint: disable=too-many-arguments
    def _update_qdisc_netem(self,
                            parent: str,
                            handle: str,
                            operation: str = 'add',  # or 'change'
                            loss_ratio: float = 0,
                            loss_correlation: int = 0,
                            duplication_ratio: int = 0,
                            duplication_correlation: int = 0,
                            delay: float = 0,
                            jitter: float = 0,
                            delay_jitter_correlation: int = 0,
                            reorder_ratio: int = 0,
                            reorder_correlation: int = 0,
                            reorder_gap: int = 0,
                            distribution: str = 'normal',
                            limit: int = 0,
                            rate: int = 0,
                            rate_packetoverhead: int = 0,
                            rate_cellsize: int = 0,
                            rate_celloverhead: int = 0,
                            slot_min_delay: float = 0,
                            slot_max_delay: float = 0,
                            slot_distribution: str = 'normal',
                            slot_delay: float = 0,
                            slot_jitter: float = 0,
                            slot_packets: int = 0,
                            slot_bytes: int = 0):
        """Enable packet loss."""

        if limit == 0:
            limit = 20000

        cmd = f'tc qdisc {operation} dev {self.interface} parent {parent} handle {handle} netem limit {limit}'

        if loss_ratio > 0:
            cmd += f' loss random {int(loss_ratio*1e2)}%'
            if loss_correlation > 0:
                cmd += f' {int(loss_correlation*1e2)}%'

        if duplication_ratio > 0:
            cmd += f' duplicate {int(duplication_ratio*1e2)}%'
            if duplication_correlation > 0:
                cmd += f' {int(duplication_correlation*1e2)}%'

        if delay > 0:
            cmd += f' delay {int(delay*1e3)}ms'
            if jitter > 0:
                cmd += f' {int(jitter*1e3)}ms'
                if delay_jitter_correlation:
                    cmd += f' {int(delay_jitter_correlation*1e2)}%'

            if distribution != 'normal':
                cmd += f' distribution {distribution}'

            if reorder_ratio > 0:
                cmd += f' reorder {int(reorder_ratio*1e2)}%'
                if reorder_correlation > 0:
                    cmd += f' {int(reorder_correlation*1e2)}%'
                if reorder_gap > 0:
                    cmd += f' gap {reorder_gap}'

        if rate > 0:
            cmd += f' rate {rate}kbit'
            if rate_packetoverhead != 0:
                cmd += f' {rate_packetoverhead}'
                if rate_cellsize > 0:
                    cmd += f' {rate_cellsize}'
                    if rate_celloverhead > 0:
                        cmd += f' {rate_celloverhead}'

        if slot_min_delay > 0 or (slot_delay > 0 and slot_jitter > 0):
            cmd += ' slot'
            if slot_min_delay > 0:
                cmd += f' {int(slot_min_delay*1e3)}ms'
                if slot_max_delay:
                    cmd += f' {int(slot_max_delay*1e3)}ms'
            else:
                cmd += f' distribution {slot_distribution} {int(slot_delay*1e3)}ms {int(slot_jitter*1e3)}ms'

            if slot_packets > 0:
                cmd += ' packets {slot_packets}'

            if slot_bytes > 0:
                cmd += ' bytes {slot_bytes}'

        self._check_call(cmd)

        return handle

    def _add_profile(self, profile: Profile):
        profile.band = self.prio_bands_avail.pop()

        self.logger.info('Assigned prio qdisc band %d to profile %s', profile.band, profile)

        handle = f'{1000+profile.band}:'
        parent = f'1:{profile.band}'

        self._check_call(f'tc filter add dev {self.interface} prio {profile.band} handle {profile.mark} fw flowid {parent}')

        netem_parameters = profile.parameters.get('netem')
        if netem_parameters:
            parent = self._update_qdisc_netem(parent=parent,
                                              handle=handle,
                                              operation='add',
                                              **netem_parameters)

    def _remove_profile(self, profile: Profile):
        if profile.band < 0:
            self.logger.warn('Profile %s has no band associated. Skipping tc removal...', profile)
            return

        self.logger.info('Removing tc filter and netem qdiscs for profile %s', profile)

        handle = f'{1000+profile.band}:'
        parent = f'1:{profile.band}'

        self._check_call(f'tc filter delete dev {self.interface} parent 1: prio {profile.band} handle {profile.mark} fw')
        self._check_call(f'tc qdisc delete dev {self.interface} parent {parent} handle {handle}')

        self._dump_tc()

        self.prio_bands_avail.add(profile.band)
        profile.band = -1

    def _update_profile(self, profile: Profile):
        netem_parameters = profile.parameters.get('netem')
        if netem_parameters:
            self._update_qdisc_netem(parent=f'1:{profile.band}',
                                     handle=f'{1000+profile.band}:',
                                     operation='change',
                                     **netem_parameters)

    def add_profile(self, profile: Profile):
        super().add_profile(profile)

        if len(self.prio_bands_avail) == 0:
            self.logger.info('No more bands in prio qdisc available. Requesting more...')

            # There are no more bands in the prio qdisc available
            # We will need to update the prio qdisc to add more bands
            self._setup_prio(bands_extra=8)

        self.logger.info('Adding tc filter and netem qdisc for profile %s', profile)
        self._add_profile(profile)

    def update_profile(self, profile: Profile):
        super().update_profile(profile)

        if profile.band < 0:
            self.logger.info('Adding netem qdisc for profile %s as it hasnt been added yet', profile)
            self._add_profile(profile)
        else:
            self.logger.info('Updating netem qdisc parameters for profile %s', profile)
            self._update_profile(profile)

    def remove_profile(self, profile: Profile):
        super().remove_profile(profile)

        self._remove_profile(profile)
