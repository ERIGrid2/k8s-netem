import datetime
import shlex
import subprocess
import sys
import time
import logging

class Impairement:
    '''Wrapper around netem module and tc commands.'''

    log = logging.getLogger('netem')

    def __init__(self, nic, inbound, include):
        self.inbound = inbound
        self.include = include if include else ['src=0/0', 'src=::/0']
        self.nic = 'ifb1' if inbound else nic
        self.real_nic = nic

    @classmethod
    def _call(cls, command):
        '''Run command.'''
        subprocess.call(shlex.split(command))

    @classmethod
    def _check_call(cls, command):
        '''Run command, raising CalledProcessError if it fails.'''
        subprocess.check_call(shlex.split(command))

    @classmethod
    def _generate_filters(cls, filter_list):
        filter_strings = []
        filter_strings_ipv6 = []
        for tcfilter in filter_list:
            filter_tokens = tcfilter.split(',')
            try:
                filter_string = ''
                filter_string_ipv6 = ''
                for token in filter_tokens:
                    token_split = token.split('=')
                    key = token_split[0]
                    value = token_split[1]
                    # Check for ipv6 addresses and add them to the appropriate
                    # filter string
                    if key == 'src' or key == 'dst':
                        if '::' in value:
                            filter_string_ipv6 += f'match ip6 {key} {value} '
                        else:
                            filter_string      += f'match ip  {key} {value} '
                    else:
                        filter_string      += f'match ip  {key} {value} '
                        filter_string_ipv6 += f'match ip6 {key} {value} '
                    if key == 'sport' or key == 'dport':
                        filter_string += '0xffff '
                        filter_string_ipv6 += '0xffff '
            except IndexError:
                cls.log.error('Invalid filter parameters')

            if filter_string:
                filter_strings.append(filter_string)

            if filter_string_ipv6:
                filter_strings_ipv6.append(filter_string_ipv6)

        return filter_strings, filter_strings_ipv6

    def initialize(self):
        '''Set up traffic control.'''
        if self.inbound:
            # Create virtual ifb device to do inbound impairment on
            self._check_call('modprobe ifb')
            self._check_call(f'ip link set dev {self.nic} up')
            # Delete ingress device before trying to add
            self._call(f'tc qdisc del dev {self.real_nic} ingress')
            # Add ingress device
            self._check_call(
                f'tc qdisc replace dev {self.real_nic} ingress')
            # Add filter to redirect ingress to virtual ifb device
            self._check_call(
                f'tc filter replace dev {self.real_nic} parent ffff: protocol ip prio 1 '
                f'u32 match u32 0 0 flowid 1:1 action mirred egress redirect '
                f'dev {self.nic}')

        # Delete network impairments from any previous runs of this script
        self._call(f'tc qdisc del root dev {self.nic}')

        # Create prio qdisc so we can redirect some traffic to be unimpaired
        self._check_call(f'tc qdisc add dev {self.nic} root handle 1: prio')

        # Apply selective impairment based on include parameters
        self.log.info('Including the following for network impairment:')
        include_filters, include_filters_ipv6 = self._generate_filters(self.include)
        
        for filter_string in include_filters:
            include_filter = f'tc filter add dev {self.nic} protocol ip parent 1:0 ' \
                             f'prio 3 u32 {filter_string}flowid 1:3'
            self.log.info(include_filter)
            self._check_call(include_filter)

        for filter_string_ipv6 in include_filters_ipv6:
            include_filter_ipv6 = f'tc filter add dev {self.nic} protocol ipv6 ' \
                                  f'parent 1:0 prio 4 u32 {filter_string_ipv6}flowid 1:3'
            self.log.info(include_filter_ipv6)
            self._check_call(include_filter_ipv6)

    # pylint: disable=too-many-arguments
    def netem(
            self,
            loss_ratio=0,
            loss_correlation=0,
            duplication_ratio=0,
            delay=0,
            jitter=0,
            delay_jitter_correlation=0,
            reorder_ratio=0,
            reorder_correlation=0,
            toggle=None):
        '''Enable packet loss.'''

        if toggle is None:
            toggle = [1000000]

        self._check_call(f'tc qdisc add dev {self.nic} parent 1:3 handle 30: netem')

        while toggle:
            impair_cmd = f'tc qdisc change dev {self.nic} parent 1:3 handle 30: ' \
                         f'netem loss {loss_ratio}% {loss_correlation}% duplicate {duplication_ratio}% ' \
                         f'delay {delay}ms {jitter}ms {delay_jitter_correlation}% ' \
                         f'reorder {reorder_ratio}% {reorder_correlation}%'
            self.log.info('Setting network impairment: %s', impair_cmd)

            # Set network impairment
            self._check_call(impair_cmd)
            self.log.info(f'Impairment timestamp: %s', datetime.datetime.today())

            time.sleep(toggle.pop(0))

            if not toggle:
                return

            self._check_call(f'tc qdisc change dev {self.nic} parent 1:3 handle 30: netem')
            self.log.info(f'Impairment stopped timestamp: %s', datetime.datetime.today())

            time.sleep(toggle.pop(0))

    def rate(self, limit=0, buffer_length=2000, latency=20, toggle=None):
        '''Enable packet reorder.'''

        if toggle is None:
            toggle = [1000000]

        self._check_call(
            f'tc qdisc add dev {self.nic} parent 1:3 handle 30: tbf rate 1000mbit '
            f'buffer {buffer_length} latency {latency}ms')

        while toggle:
            impair_cmd = f'tc qdisc change dev {self.nic} parent 1:3 handle 30: tbf ' \
                         f'rate {limit}kbit buffer {buffer_length} latency {latency}ms'
            self.log.info('Setting network impairment: %s', impair_cmd)

            # Set network impairment
            self._check_call(impair_cmd)
            self.log.info(f'Impairment timestamp', datetime.datetime.today())

            time.sleep(toggle.pop(0))

            if not toggle:
                return

            self._check_call(
                f'tc qdisc change dev {self.nic} parent 1:3 handle 30: tbf rate '
                f'1000mbit buffer {buffer_length} latency {latency}ms')

            self.log.info(f'Impairment stopped timestamp: %s', datetime.datetime.today())

            time.sleep(toggle.pop(0))

    def teardown(self):
        '''Reset traffic control rules.'''
        if self.inbound:
            self._call(f'tc filter del dev {self.real_nic} parent ffff: protocol ip prio 1')
            self._call(f'tc qdisc del dev {self.real_nic} ingress')
            self._call(f'ip link set dev ifb0 down')

        self._call(f'tc qdisc del root dev {self.nic}')

        self.log.info('Network impairment teardown complete.')
