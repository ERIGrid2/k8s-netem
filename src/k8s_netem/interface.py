import os
import re


def get_default_route_interface():
    """Read the default gateway directly from /proc."""

    with open('/proc/net/route') as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] == '00000000' and fields[7] == '00000000':
                return fields[0]

    return None


def get_interfaces(filter: str = None):
    """ Find suitable interface """

    intfs = os.listdir('/sys/class/net')
    intfs.sort()

    if filter is None:
        return intfs

    e = re.compile(filter)

    return [i for i in intfs if e.match(i) is not None]


def get_interface_index(intf: str) -> int:
    with open(f'/sys/class/net/{intf}/ifindex') as f:
        return int(f.read())
