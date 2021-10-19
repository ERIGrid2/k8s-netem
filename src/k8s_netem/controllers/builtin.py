from k8s_netem.controller import Controller


class BuiltinController(Controller):
    """Wrapper around netem module and tc commands."""

    def __init__(self, ingress: bool, filters: list = []):
        self.ingress = ingress
        self.filters = filters

        self.type = 'Builtin'

    def _initialize_ingress(self):
        # Create virtual ifb device to do ingress impairment on
        self._check_call('modprobe ifb')
        self._check_call(f'ip link set dev {self.interface} up')

        # Delete ingress device before trying to add
        self._call(f'tc qdisc del dev {self.real_interface} ingress')

        # Add ingress device
        self._check_call(f'tc qdisc replace dev {self.real_interface} ingress')

        # Add filter to redirect ingress to virtual ifb device
        self._check_call(
            f'tc filter replace dev {self.real_interface} parent ffff: protocol ip prio 1 '
            f'u32 match u32 0 0 flowid 1:1 action mirred egress redirect '
            f'dev {self.interface}')

    def _deinitialize_ingress(self):
        self._call(f'tc filter del dev {self.real_interface} parent ffff: protocol ip prio 1')
        self._call(f'tc qdisc del dev {self.real_interface} ingress')
        self._call('ip link set dev ifb0 down')

    def init(self, interface: str, options: dict):
        """Set up traffic control."""

        self.real_interface = interface
        self.interface = 'ifb1' if self.ingress else interface

        if self.ingress:
            self._initialize_ingress()

        # Delete network impairments from any previous runs of this script
        self._call(f'tc qdisc del root dev {self.interface}')

        # Create prio qdisc so we can redirect some traffic to be unimpaired
        self._check_call(f'tc qdisc add dev {self.interface} root handle 1: prio')

        # Apply selective impairment based on filter parameters
        for filter in self.filters:
            self._check_call(f'tc filter add dev {self.interface} protocol ip parent 1:0 prio 3 basic match {filter} flowid 1:3')

        self.apply(options)

    def deinit(self):
        """Reset traffic control rules."""

        if self.ingress:
            self._deinitialize_ingress()

        self._call(f'tc qdisc del root dev {self.interface}')

    def apply(self, options: dict):
        if 'netem' in options:
            self.netem(**options['netem'])

        if 'rate' in options:
            self.rate(**options['rate'])

    # pylint: disable=too-many-arguments
    def netem(self,
              loss_ratio: int = 0,
              loss_correlation: int = 0,
              duplication_ratio: int = 0,
              delay: int = 0,
              jitter: int = 0,
              delay_jitter_correlation: int = 0,
              reorder_ratio: int = 0,
              reorder_correlation: int = 0):
        """Enable packet loss."""

        self._check_call(f'tc qdisc add dev {self.interface} parent 1:3 handle 30: netem '
                         f'loss {loss_ratio}% {loss_correlation}% '
                         f'duplicate {duplication_ratio}% '
                         f'reorder {reorder_ratio}% {reorder_correlation}%'
                         f'delay {delay}ms {jitter}ms {delay_jitter_correlation}% ')

    def rate(self,
             limit: int = 0,
             buffer_length: int = 2000,
             latency: int = 20):
        """Enable packet reorder."""

        self._check_call(f'tc qdisc add dev {self.interface} parent 1:3 handle 30: tbf '
                         f'rate {limit}kbit '
                         f'buffer {buffer_length} '
                         f'latency {latency}ms')
