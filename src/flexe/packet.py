'''FLEXE Network Emulator

Copyright 2022, VTT Technical Research Centre of Finland Ltd.

The above copyright notice and this license notice shall be included in all copies
or substantial portions of the Software

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

@author: Markku Savela <Markku.Savela(at)vtt.fi>
@author: Kimmo Ahola <Kimmo.Ahola(at)vtt.fi>

'''

import socket
import select
import collections
import netaddr
from base64 import b64encode, b64decode
from binascii import hexlify, unhexlify
import flexe.lib.networking as net
import hashlib
import time
import traceback
import sys
import os
import glob
import subprocess
from threading import Timer

IF_ALL = (1 << 53) - 1

THROTTLE_DELAY = 0.2
HEART_BEAT = 1.0

KEYPACK = [
    (6, 'mac', 'dmac', 'Destination MAC address'),
    (6, 'mac', 'smac', 'Source MAC address'),
    (2, 'int', 'vlan1', None),  # 'First VLAN tag' -- not available now
    (2, 'int', 'vlan2', None),  # 'Secong VLAN tag' -- not available now
    (2, 'hex', 'type', 'Ethernet Type'),
    (1, 'int', 'ipv', 'IP version value'),
    (16, 'ip', 'src', 'IP source address/prefix'),
    (16, 'ip', 'dst', 'IP destination address/prefix'),
    (1, 'int', 'proto', 'IP Transport Protocol'),
    (2, 'int', 'sport', 'UDP/TCP source port'),
    (2, 'int', 'dport', 'UDP/TCP destination port or ICMP (type<<8|code)'),
    (1, 'int', 'iface', 'Interface number'),
    (4, 'int', 'fwmark', 'Firewall mark')
]
# Key length in bytes
KEY_LENGTH = sum(f[0] for f in KEYPACK)
KEY_FMT = '%%0%dx' % (2*KEY_LENGTH)

# This tells the GUI client the supported profile parameters.

PROFILE_INT_MS = {'type': 'int', 'unit': 'ms'}
PROFILE_INT_S = {'type': 'int', 'unit': 's'}
PROFILE_INT_PERCENT = {'type': 'int', 'unit': '%'}
PROFILE_INT_KBPS = {'type': 'int', 'unit': 'Kbps'}
PROFILE_DELAY_DISTRIBUTION = {'type': 'select',
                              'option': ['', 'uniform', 'normal', 'pareto', 'paretonormal']}

PROFILE_TEMPLATE = [
    {},
    {
        'label': 'Bandwidth up:',
        'name': 'bandwidthUp',
        'value': PROFILE_INT_KBPS,
        'help': ('Emulated bit rate to use when flow represents the "upload" direction.')
    },
    {
        'label': 'Bandwidth Down:',
        'name': 'bandwidthDown',
        'value': PROFILE_INT_KBPS,
        'help': ('Emulated bit rate to use when flow represents the "download" direction.')
    },
    {},
    {
        'label': 'Delay:',
        'name': 'delay',
        'value': PROFILE_INT_MS,
        'help': ('Set a delay to the packets of the flow. The computed '
                 'delay is a combination of parameters '
                 '<p style="text-align: center;"><i>delay</i> \u00b1 <i>variation</i>,</p> with next random '
                 'element depending on previous value by the <i>correlation</i> percentace.')
    },
    {
        'label': 'Delay variation:',
        'name': 'delayVariation',
        'value': PROFILE_INT_MS
    },
    {
        'label': 'Delay correlation:',
        'name': 'delayCorrelation',
        'value': PROFILE_INT_PERCENT
    },
    {
        'label': 'Distribution:',
        'name': 'delayDistribution',
        'value': PROFILE_DELAY_DISTRIBUTION,
        'help': ('If a distribution is selected, <b>the delay variation, '
                 'must have a non-zero value</b>.')
    },
    {},
    {
        'label': 'Packet loss:',
        'name': 'loss',
        'value': PROFILE_INT_PERCENT,
        'help': ('Set the percentage of the packet '
                 'loss. The <i>correlation</i> defines the percentage by'
                 'which the next random loss depends on the previous '
                 'value. This can be used to simulate packet losses in '
                 'bursts.')
    },
    {
        'label': 'Loss correlation:',
        'name': 'lossCorrelation',
        'value': PROFILE_INT_PERCENT,
    },
    {
        'label': 'Duplicates:',
        'name': 'duplication',
        'value': PROFILE_INT_PERCENT,
        'help': ('Set the percentage of the packet duplication.')
    },
    {
        'label': 'Corruption:',
        'name': 'corruption',
        'value': PROFILE_INT_PERCENT,
        'help': ('Set the percentage of the packet corruption by '
                 'generated random noise.')
    },
    {},
    {
        'label': 'Reorder:',
        'name': 'reorder',
        'value': PROFILE_INT_PERCENT,
        'help': ('Set the percentage of the packets that get '
                 'reordered. The <i>correlation</i> defines the percentage '
                 'of next random value depending on the previous one. '
                 '<p>Note: <i>reorder</i> requires non-zero delay setting '
                 'to be effective.')
    },
    {
        'label': 'Reorder correlation:',
        'name': 'reorderCorrelation',
        'value': PROFILE_INT_PERCENT
    },
    {},
    {
        'name': 'runTime',
        'value': PROFILE_INT_S
    }
]

CLIENTS: set = set()


def log(client, msg):
    print(msg, flush=True)


def bytes_to_int(s):
    """Convert key byte array to a long integer
    """
    return int(hexlify(s), 16)


def int_to_bytes(key):
    """Convert integer key into bytes array
    """
    return unhexlify(KEY_FMT % key)


def filter_key_mask(source, target):
    """Generate filter key and mask for source/target socket addresses
    """
    key = ''
    mask = ''
    for field in KEYPACK:
        if field[2] == 'src':
            key += netaddr.IPAddress(source[0]).ipv6().__str__()
            mask += '\xff' * field[0]
        elif field[2] == 'dst':
            key += netaddr.IPAddress(target[0]).ipv6().__str__()
            mask += '\xff' * field[0]
        elif field[2] == 'sport':
            key += chr(source[1] >> 8) + chr(source[1] & 0xff)
            mask += '\xff' * field[0]
        elif field[2] == 'dport':
            key += chr(target[1] >> 8) + chr(target[1] & 0xff)
            mask += '\xff' * field[0]
        else:
            key += '\0' * field[0]
            mask += '\0' * field[0]
    return (bytes_to_int(bytes(key, "utf-8")), bytes_to_int(bytes(mask, "utf-8")))


class ServerHandle(net.Network):
    """Listening socket

    Each instance represents a listening socket on the server.

    The instance is a plain Network object. The only addition is to
    set the 'isserver' attribute to True, so that the main loop knows
    to issue 'accept' instead of 'read' action, when the socket
    becomes readable.
    """
    isserver = True
    id = 0


class ServiceError(Exception):
    pass


class ClientHandle(net.Network):
    """Connected Client Socket

    Each instance represents a connected client socket created by the
    'accept' action on the listening server socket.
    """
    isserver = False
    id = 0

    def __init__(self, address, sock):
        net.Network.__init__(self, socktype=socket.SOCK_STREAM, sct=sock)
        ClientHandle.id += 1
        self.id = ClientHandle.id
        self.websocket = False
        self.msg = ''
        self.field = None
        self.header = {}
        self.linenr = 0
        self.notify = False  # set True, when client is ready to receive countup's
        self.filter_id = None
        self.filters = []
        self.profiles = None
        self.user = 'unknown'
        self.run_profiles = None
        self.profile_data = None
        self.timemark = 0
        self.throttle_delay = THROTTLE_DELAY
        self.heart_beat = HEART_BEAT

        peername = self.getpeername()
        sockname = self.getsockname()
        self.client_addr = peername[0]

        self.inbound = filter_key_mask(peername, sockname)
        self.outbound = filter_key_mask(sockname, peername)

        self.interfaces = 0  # bitmask of interfaces configured
        log(self, "got client {} peer={} sock={}".format(self.id, peername, sockname))

    def _tc_run(self, command, timeout=5):
        """ Run sub-process with a time limit.

        Args:
            command: Sub-process command.
            timeout: Value in seconds.

        """
        def kill_proc(p):
            p.kill()

        log(self, "--- " + command)  # KISAAH
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, shell=True)
        timer = Timer(timeout, kill_proc, [proc])
        timer.start()
        out, err = proc.communicate()
        timer.cancel()
        send_to_all(CLIENTS, {'id': TCCOMMAND,
                              'cmd': command,
                              'out': out,
                              'err': err,
                              'stamp': time.time()})

    def _tc_filter(self, filter):
        selector = ''
        mac_selector = ''
        protocol = 'ip'
        ipv = 'ip'
        shift = KEY_LENGTH * 8
        for length, type, name, _ in KEYPACK:
            # Transform field into integer
            bits = length * 8
            bmask = (1 << bits) - 1
            shift -= bits
            value = (filter[0] >> shift) & bmask
            mask = (filter[1] >> shift) & bmask

            if mask == 0:
                continue

            if name in {'vlan1', 'vlan2'}:
                raise ServiceError("Filtering based on vlan not yet supported: " + name)

            if type == 'ip':
                value = netaddr.IPAddress(value, 6)
                mask = netaddr.IPAddress(mask, 6)
                if (int(value) == 0 and ipv == 'ip') or (0xffff00000000 <= int(value) <= 0xffffffffffff):
                    # IPv4 mapped address
                    mask = netaddr.IPAddress(int(mask) & 0xffffffff, 4)
                    value = value.ipv4()
                    net = netaddr.IPNetwork(str(value) + "/" + str(mask))
                    if net.prefixlen == 32:
                        net = value
                    selector += ' match ip {} {}'.format(name, str(net))
                    protocol = 'ip'
                    ipv = 'ip'
                else:
                    net = netaddr.IPNetwork(str(value) + "/" + str(mask))
                    if net.prefixlen == 128:
                        net = value
                    selector += ' match ip6 {} {}'.format(name, str(net))
                    protocol = 'ipv6'
                    ipv = 'ip6'
            elif name == 'ipv':
                print(name, value)
                if value == 6:
                    # Assume 'protocol=ipv6' does the
                    # filtering, and don't install any
                    # specific match for the on-the-wire
                    # protocol number
                    protocol = 'ipv6'
                    ipv = 'ip6'
            elif name == 'proto':
                selector += ' match {} protocol {} {:#02x}'.format(ipv, value, mask)
                if value == 1:
                    ipv = 'icmp'
                    protocol = 'ip'
                elif value == 58:
                    ipv = 'icmp'
                    protocol = 'ipv6'
                elif value == 6:
                    ipv = 'tcp'
                elif value == 17:
                    ipv = 'udp'
            elif name == 'sport' or name == 'dport':
                if ipv == 'icmp':
                    if name == 'dport':
                        selector += ' match icmp type {} {:#02x}'.format(value >> 8, mask >> 8)
                        selector += ' match icmp code {} {:#02x}'.format(value & 0xff, mask & 0xff)
                elif ipv == 'tcp' or ipv == 'udp':
                    name = 'src' if name == 'sport' else 'dst'
                    selector += ' match {} {} {} {:#04x}'.format(ipv, name, value, mask)
                else:
                    selector += ' match {} {} {} {:#04x}'.format(ipv, name, value, mask)
            elif name == 'smac':
                selector += ' match ether src ' + _mac(value)
            elif name == 'dmac':
                selector += ' match ether dst ' + _mac(value)
            elif name == 'iface':
                # This indicates either inbound or outbound interface,
                # if present, limits flow exactly to packets coming in
                # or going out from that interface, and there is only
                # one bit set either in inb or out. If in 'inb' we
                # don't get here, and if in 'out' we are already
                # installing netem on that. => 'iface' really should
                # not be included in filter spec!
                pass
            elif name == "type":
                # If Ethernet type is IP, then there is no need to anything
                # But if the Ethernet Type is something else, there is need to change protocol type
                # and selector.
                if value != 2048:
                    print("DEBUG: Not IP packet -> act accordingly")
                    protocol = 'all'
                    mac_selector = 'u32 match u16 {:#04x} 0xffff at -2'.format(value)
                    break
                else:
                    print("DEBUG: IP packet -> do nothing")
                # print("DEBUG: Type = Ethernet type, selector = {}, value = {}, mask = {}".format(selector, value, mask))
            elif name == "fwmark":
                # If the "type" == int and name == "fwmark", then only use fw_mark as a filter
                protocol = 'fw'
                selector = "handle {}".format(value & mask)
            else:
                raise ServiceError("Unsupported filter: " + name)

        if selector == '':
            # Add dummy "match all", if nothing else matched
            selector += ' match u8 0 0'

        if protocol == 'ipv6':
            selector = 'u32 ht 6:' + selector
        elif protocol == 'ip':
            selector = 'u32 ht 4:' + selector
        elif protocol == 'all':
            selector = mac_selector

        return (protocol, selector)

    def _load_profile(self, profile):
        # profile is interpreted as:
        #
        #   name - try "name@user" first and then "name"
        #   name@host - try only "name@host"
        #
        profile = profile.strip()
        if profile == '':
            return None

        # If already loaded, just return current state
        data = self.run_profiles.get(profile)
        if data is not None:
            return data

        data = self.profile_data.get(profile)
        if data is None:
            raise ServiceError("profile '{}' has not been provided by client".format(profile))

        head = {}
        self.run_profiles[profile] = head
        terminate = time.time()
        start = data['run']['start']
        end = data['run']['end']
        for index, curr in enumerate(data['segments'][0:end]):
            head.update(curr)
            if index < start:
                continue
            head['index'] = index
            duration = head.get('runTime')
            if duration is not None and duration > 0:
                # Convert duration (runTime) into absolute time stamp that
                # indicates the end of life for this (head) segment.
                terminate += duration
                head['lifeTime'] = terminate
                break

        # If runTime of the last segment is 0, then it remains zero
        # (lifeTime is not set) and is interpreted as infinite run
        # time (no specific end of life time stamp).
        return head

    def _tc_netem(self, data, uplink):
        if data is None:
            return ''
        netem = 'netem'
        value = data.get('delay')
        if value:
            variation = data.get('delayVariation', 0)
            netem += ' delay {}ms {}ms'.format(value, variation)
            correlation = data.get('delayCorrelation', 0)
            if correlation > 0:
                netem += ' {}%'.format(correlation)
        value = data.get('delayDistribution')
        if value and value in PROFILE_DELAY_DISTRIBUTION['option']:
            netem += ' distribution ' + value
        value = data.get('loss', 0)
        correlation = data.get('lossCorrelation', 0)
        if correlation > 0 or value > 0:
            netem += ' loss {}%'.format(value)
            if correlation > 0:
                netem += ' {}%'.format(correlation)
        value = data.get('duplication')
        if value:
            netem += ' duplicate {}%'.format(value)
        value = data.get('duplication')
        if value:
            netem += ' corrupt {}%'.format(value)
        value = data.get('reorder', 0)
        correlation = data.get('reorderCorrelation', 0)
        if correlation > 0 or value > 0:
            netem += ' reorder {}%'.format(value)
            if correlation > 0:
                netem += ' {}%'.format(correlation)
        if uplink:
            value = data.get("bandwidthUp")
        else:
            value = data.get("bandwidthDown")
        if value:
            netem += ' rate {}kbit'.format(value)
        return netem

    def unrun(self, INTERFACES):
        # Remove previous configuration and return bitmask of initialized interfaces
        self.run_profiles = {}
        self.profile_data = None
        self.profiles = None
        initialized = 0
        for iface in iter(INTERFACES.values()):
            if iface[1] & self.interfaces:
                initialized |= iface[1]
                self._tc_run('tc qdisc del dev {} root'.format(iface[0]))
        self.interfaces = 0
        return initialized

    def rerun(self, INTERFACES, delay):
        redo = set()
        now = time.time()

        # Check for expired profile segments
        for egress, profile in iter(self.run_profiles.items()):
            if profile is None:
                continue
            lifetime = profile.get('lifeTime', 0)
            if lifetime == 0:
                continue
            if lifetime > now:
                alive = lifetime - now
                if alive < delay:
                    delay = alive
                continue

            data = self.profile_data.get(egress)
            if data is None:
                continue  # This is an error (should not happen)

            start = profile['index'] + 1
            end = data['run']['end']
            redo.add(egress)  # changing segment, some tc update will be needed
            for index, curr in enumerate(data['segments'][start:end], start=start):
                profile.update(curr)
                profile['index'] = index
                duration = profile.get('runTime')
                if duration > 0:
                    # Convert duration (runTime) into absolute time stamp that
                    # indicates the end of life for this (head) segment.
                    lifetime += duration
                    profile['lifeTime'] = lifetime
                    break
                # Duration == profile['runTime'] == 0 (segments with
                # zero runTime are ignored, except as the last
                # segment).
            else:
                # No live segments left, the profile represents the last segment.
                lifetime = profile.get('runTime', 0)
                if lifetime != 0:
                    self.run_profiles[egress] = None
                    if data['run'].get('repeat'):
                        self._load_profile(egress)
                else:
                    del profile['lifeTime']

        if len(redo) == 0:
            # log(self, "delay: {} -- no redo".format(delay))
            return delay, None

        # Record actual profiles used
        if self.profiles is None:
            # log(self, "delay: {} -- no profiles".format(delay))
            return delay, None
        i = 0
        profiles_used = {}
        classes = {}
        for filter in self.filters:
            info = filter[2]
            egress = self.profiles[i][1]
            i += 1
            if not egress:
                continue  # filter does not have netem
            netem = classes.get((egress, info.dir))
            if netem is None:
                profile = self.run_profiles[egress]
                if profile is not None:
                    profiles_used[egress] = profile
                    # if egress not in redo:
                    #     continue # No change in this profile
                    netem = self._tc_netem(profile, info.dir)
                    classes[(egress, info.dir)] = netem
                else:
                    netem = 'netem'  # Remove profile for this filter
            minor = 10 + i
            if egress not in redo:
                continue
            for iface in iter(INTERFACES.values()):
                if iface[1] & info.out:
                    if netem:
                        self._tc_run('tc qdisc replace dev {} parent 1:{:X} handle {:X}: {}'.format(iface[0], minor, i*10, netem))
        if len(profiles_used) == 0:
            # No profiles left, terminate application cleanly (remove all definitions)
            self.unrun(INTERFACES)
        # log(self, "delay: {} -- profiles {}".format(delay, str(profiles_used)))
        return delay, profiles_used

    def run(self, msg, INTERFACES):
        # msg = {
        #   id: "RunApplication",
        #   user: <user_name>
        #   fid: <filter id>
        #   profiles: [ [<ingress profile>, <egress profile>], ...]
        #   profile_data: {
        #     <profilename>: {
        #       ...
        #       segments: [<profile segment>,...],
        #       ...
        #     }
        #   }
        # }
        initialized = self.unrun(INTERFACES)
        self.run_profiles = {}
        self.profiles = msg.get('profiles')
        self.profile_data = msg.get('profile_data', {})

        if self.filter_id != msg.get('fid'):
            raise ServiceError("Filter id mismatch")

        # Record actual profile segments in use
        profiles_used = {}
        if self.profiles is None:
            return profiles_used

        if len(self.filters) != len(self.profiles):
            raise ServiceError("Incorrect number of profiles")

        i = 0
        classes = {}
        print("KISAAH: Nyt alkaa testaaminen")
        for filter in self.filters:
            info = filter[2]
            egress = self.profiles[i][1]
            i += 1
            if egress:
                netem = classes.get((egress, info.dir))
                if netem is None:
                    data = self._load_profile(egress)
                    netem = self._tc_netem(data, info.dir)
                    profiles_used[egress] = data
                    classes[(egress, info.dir)] = netem
                minor = 10 + i
            else:
                minor = 1
                netem = None
            protocol, selector = self._tc_filter(filter)

            print("DEBUG: Now protocol = {} and selector = {}, egress = {}, netem = {}".format(protocol, selector, egress, netem))

            for iface in iter(INTERFACES.values()):
                if iface[1] & info.out:
                    fp = 'tc filter add dev {} '.format(iface[0])
                    if (iface[1] & self.interfaces) == 0:
                        # Initialize only new interfaces
                        if (iface[1] & initialized) == 0:
                            self._tc_run('tc qdisc del dev {} root'.format(iface[0]))
                            initialized |= iface[1]
                        self.interfaces |= iface[1]
                        self._tc_run('tc qdisc add dev {} handle 1: root htb'.format(iface[0]))
                        self._tc_run('tc class add dev {} parent 1: classid 1:1 htb rate 1000Mbps'.format(iface[0]))

                        # The following commands are run only when filter protocol is IP
                        if protocol == "ip":
                            self._tc_run(fp + 'parent 1: protocol ip handle 4: u32 divisor 1')
                            self._tc_run(fp + 'parent 1: protocol ipv6 handle 6: u32 divisor 1')
                            self._tc_run(fp + 'parent 1: protocol ip u32 ht 800: match u8 0 0 offset at 0 mask 0f00 shift 6 link 4:')
                            self._tc_run(fp + 'parent 1: protocol ipv6 u32 ht 800: match u8 0 0 offset plus 40 link 6:')
                    if netem:
                        self._tc_run('tc class add dev {} parent 1:1 classid 1:{:X} htb rate 100Mbps'.format(iface[0], minor))
                        self._tc_run('tc qdisc add dev {} parent 1:{:X} handle {:X}: {}'.format(iface[0], minor, i*10, netem))

                    if protocol == "fw":
                        self._tc_run(fp + "{} {} classid 1:{:X}".format(selector, protocol, minor))
                    else:
                        self._tc_run(fp + 'protocol {} prio {} {} flowid 1:{:X}'.format(protocol, i, selector, minor))
        return profiles_used

    def error(self, request, reason):
        self.send({'id': 'error', 'result': reason, 'request': request})

    def match_self(self, f):
        # Test if flow matches the client connection
        if (f.key ^ self.outbound[0]) & self.outbound[1]:
            # No match on outbound, test inbound
            if (f.key ^ self.inbound[0]) & self.inbound[1]:
                # No match on inbound
                return False
        return True

    def filter_flow(self, f):
        # Update filter specific counts. f is an instance of CountUp.
        for filter in self.filters:
            if (f.key ^ filter[0]) & filter[1]:
                continue

            info = filter[2]
            if (info.inb & f.inb) == 0 and (info.out & f.out) == 0:
                continue
            # filter matched
            info.inb_count += f.inb_delta
            info.out_count += f.out_delta
            info.time = f.time
            return True
        return False

    def flush_counts(self):
        if len(self.filters) == 0:
            return  # Nothing to do
        counts = []
        i = 0
        for filter in self.filters:
            info = filter[2]
            if (info.inb_count or info.out_count):
                counts.append((i, info.inb_count, info.out_count, info.time))
                info.inb_count = 0
                info.out_count = 0
            i += 1
        if len(counts) == 0:
            # All filters had zero counts, this must be "heart beat" call, add a dummy counts element
            counts.append((0, 0, 0, time.time()))
        self.send({'id': 'filter',
                   'fid': self.filter_id,
                   'cnt': counts})

    def check_send(self, msg):
        ret = self._socket.send(bytes(msg, "utf-8"))
        if ret != len(msg):
            log("{} != {} for '{}'".format(ret, len(msg), msg))

    def rcve_async(self, do_read=True):
        while True:
            if self.websocket:
                log(self, "KISAAH: Websocket data")
                return super(ClientHandle, self).rcve_async(do_read)

            if self.msg is None:
                raise EOFError

            line, sep, after = self.msg.partition('\r\n')
            if sep == '':
                if not do_read:
                    return None
                # No line end available, read more
                chunk = self._socket.recv(4096)
                if chunk == '':
                    # No more data available
                    if line == '':
                        self.msg = None
                        raise EOFError
                    after = None
                    # 'after' goes into self.msg and creates a persistent
                    # EOF state -- any attempt to use rcve after this will
                    # raise EOFError. NOTE: the last line is without line
                    # end, but this is hidden from the user of this api...
                else:
                    # Check if the new chunk has the line end
                    chunk, sep, after = chunk.decode("utf-8").partition('\r\n')
                    line = line + chunk
                    if sep == '':
                        # Still no line end, keep buffering
                        self.msg = line
                        return None
                    # Line end foud
            self.msg = after
            if line == '':
                # End Of Headers
                log(self, "Handshaking...")
                key = self.header.get('sec-websocket-key')
                if key is None:
                    raise socket.error("Missing Sec-WebSocket-Key header")
                ver = self.header.get('sec-websocket-version')
                if ver != '13':
                    raise socket.error("Unsupported WebSocket version {}".format(ver))
                if self.header.get('upgrade').lower() != 'websocket':
                    raise socket.error("Request is not websocket upgrade")
                hash = hashlib.sha1()
                # hash.update(key)
                hash.update(bytes(key, "utf-8"))
                hash.update(bytes('258EAFA5-E914-47DA-95CA-C5AB0DC85B11', "utf-8"))
                hash_base64 = b64encode(hash.digest()).decode("utf-8")
                self.check_send('HTTP/1.1 101 Switching Protocols\r\n')
                self.check_send('Upgrade: websocket\r\n')
                self.check_send('Connection: Upgrade\r\n')
                # self.check_send('Sec-WebSocket-Accept: ' + b64encode(hash.digest()) + '\r\n')
                self.check_send('Sec-WebSocket-Accept: ' + hash_base64 + '\r\n')
                self.check_send('\r\n')
                self.websocket = True
                log(self, "Handshaking complete...")
            elif self.linenr == 0:
                # This line should be the GET request
                parts = line.strip().split()
                if len(parts) < 3 or parts[0] != 'GET':
                    raise socket.error("Invalid request line: '{}'".format(line))
                self.path = parts[1]
            elif line.startswith(' ') or line.startswith('/t'):
                log(self, "got continuation")
                # This is a continuation line for previous field
                if self.field is None:
                    raise socket.error("Invalid header continuation line: '{}'".format(line))
                self.header[self.field] += ' ' + line.strip()
            else:
                # This must be a new field
                line = line.strip()
                self.field, sep, value = line.partition(':')
                if sep != ':':
                    raise socket.error("Invalid header line: '{}'".format(line))
                self.field = self.field.strip().lower()
                value = value.strip()
                if self.field in self.header:
                    self.header[self.field] += ',' + value
                else:
                    self.header[self.field] = value
            self.linenr += 1
            log(self, line)


def _mac(mac):
    a = netaddr.EUI(mac)
    a.dialect = netaddr.mac_unix
    return str(a)


def _ip(a, v):
    if (v):
        return str(netaddr.IPAddress(a, v))
    else:
        return a


class Info:
    def __init__(self, inb=None, out=None, dir=False):
        self.inb = IF_ALL if inb is None else inb
        self.inb_count = 0
        self.out = IF_ALL if out is None else out
        self.out_count = 0
        self.dir = dir
        self.time = None

    def json(self):
        return {
            'inb_count': self.inb_count,
            'out_count': self.out_count,
            'time': self.time
        }


class CountUp(collections.namedtuple('CountUp', ['key', 'inb', 'inb_delta', 'out', 'out_delta', 'time'])):
    pass


QUIT = 'Quit'
GETPACKING = 'GetPacking'
SETFILTERS = 'SetFilters'
SETCONTROL = 'SetControl'
RUNAPPLICATION = 'RunApplication'
NEWINTERFACE = 'NewInterface'
PROFILETEMPLATE = 'ProfileTemplate'
TCCOMMAND = 'TcCommand'


def send_to_all(clients, msg, butone=None):
    for c in clients:
        if c is not butone:
            c.send(msg)


def exporter():
    print("exporter pid=", os.getpid())
    wss = ServerHandle()
    wss.createServerSocket(('', 8888))

    INTERFACES = {key: (key, 1 << value, value) for (value, key) in enumerate(os.listdir('/sys/class/net'))}  # Hash of detected interfaces

    # Currently running filter (as client instance)
    running = None

    # WARNING: Queue _reader as select works only in linux!
    WATCHED = [wss]
    busy = True
    cycles = 0
    timeout = 2

    # The 'update_counts' is the set of clients (id's) which are
    # pending for the packet count message to be sent.
    update_counts = set()

    while busy:
        if (cycles & 0xffff) == 0:
            print("exporter cycles=", cycles)
        cycles += 1

        (sread, swrite, sexc) = select.select(WATCHED, [], WATCHED, timeout)
        timeout = 2

        for c in CLIENTS:
            timemark = time.time()
            passed = timemark - c.timemark
            if passed < 0:
                # Not enough time has passed for this client since
                # last flush, don't send anything yet (throttling).
                if (timeout > -passed):
                    timeout = -passed
                continue
            if c in update_counts:
                update_counts.remove(c)
                if timeout > c.heart_beat:
                    timeout = c.heart_beat
            elif passed < c.heart_beat:
                if c.heart_beat - passed < timeout:
                    timeout = c.heart_beat - passed
                continue  # idle, no packet changes

            # throttle_delay prevents sending of excessive
            # amount of packet count messages (update_counts
            # remains set for such client and sending happens
            # later)
            c.timemark = timemark + c.throttle_delay
            try:
                c.flush_counts()
            except Exception as e:
                # NOTE: this branch is most likely untested...
                print("closing client: " + str(c.id) + " error: " + str(e))
                if c is running:
                    c.unrun(INTERFACES)
                    c.close()

        if running is not None:
            timeout, used = running.rerun(INTERFACES, timeout)
            if used is not None:
                reply = {
                    'id': RUNAPPLICATION,
                    'stamp': time.time(),
                    'client': 0,
                    'fid': running.filter_id,
                    'interfaces': running.interfaces,
                    'profiles': used
                }
                running.send(reply)
                reply['client'] = running.user + ':' + str(running.id)
                send_to_all(CLIENTS, reply, butone=running)

        for rdy in sread:
            if rdy.isserver:
                (conn, addr) = rdy.socket().accept()
                client = ClientHandle(addr, conn)
                WATCHED.append(client)
                CLIENTS.add(client)
            else:
                do_read = True
                try:
                    while True:
                        msg = rdy.rcve_async(do_read)
                        if msg is None:
                            break
                        print("GOT:", msg)
                        try:
                            id = msg.get('id')
                            print("KISAAH: id = {}".format(id))
                            if 'user' in msg:
                                rdy.user = msg['user']

                            if id == GETPACKING:
                                rdy.send({'id': GETPACKING, 'result': KEYPACK})
                                # This is ugly hack, was working better in python2
                                # Without this, json.dumps will error "Circular reference detected"
                                j = []
                                for i in INTERFACES.values():
                                    j.append(list(i))
                                rdy.send({'id': NEWINTERFACE, 'result': j})
                                rdy.send({'id': PROFILETEMPLATE, 'result': PROFILE_TEMPLATE})
                                rdy.notify = True
                            elif id == SETFILTERS:
                                rdy.filter_id = msg.get('fid')
                                rdy.filters = [[bytes_to_int(b64decode(x[0])),
                                                bytes_to_int(b64decode(x[1])),
                                                Info(x[2], x[3], x[4])] for x in msg.get('filters')]
                            elif id == SETCONTROL:
                                # Min counters reporting frequency in seconds
                                rdy.throttle_delay = msg.get('frequency', rdy.throttle_delay)
                                rdy.heart_beat = msg.get('heartbeat', rdy.heart_beat)
                            elif id == RUNAPPLICATION:
                                # msg = {
                                #   id: "RunApplication",
                                #   user: <user_name>
                                #   fid: <filter id>
                                #   profiles: [ [<ingress profile>, <egress profile>], ...]
                                #   profile_data: {
                                #     <profilename>: {
                                #        ...
                                #        segments: [<profile segment>,...],
                                #        ...
                                #     }
                                #   }
                                # }
                                #
                                print("KISAAH: oli runapplication")
                                if running is not None and running is not rdy:
                                    running.unrun(INTERFACES)

                                print("KISAAH: Now call clienthandle.run")
                                used = rdy.run(msg, INTERFACES)
                                # 'used' is a dictionary of profiles
                                # (key is the profile name)
                                running = rdy
                                reply = {
                                    'id': RUNAPPLICATION,
                                    'stamp': time.time(),
                                    'client': 0,
                                    'fid': rdy.filter_id,
                                    'interfaces': rdy.interfaces,
                                    'profiles': used
                                }
                                pl = msg.get('profiles')
                                if pl is None:
                                    # profiles == None => stop running
                                    running = None
                                else:
                                    # Filters is an array of tuples:
                                    #  0: profile name
                                    #  1: filter value
                                    #  2: filter mask
                                    #  3: uplink (true), downlink (false)
                                    reply['filters'] = [(pl[i],
                                                         b64encode(int_to_bytes(f[0])),
                                                         b64encode(int_to_bytes(f[1])),
                                                         f[2].dir) for i, f in enumerate(rdy.filters)]
                                # client==0 indicates own application for the client
                                rdy.send(reply)
                                # Inform all other clients
                                reply['client'] = rdy.user + ':' + str(rdy.id)
                                send_to_all(CLIENTS, reply, butone=rdy)
                            else:
                                rdy.error(msg, "Not implemented")
                        except ServiceError as e:
                            rdy.error(msg, str(e))
                        do_read = False
                except Exception as e:
                    print("*** Closing client: {} ***".format(str(e)))
                    print('-'*60)
                    traceback.print_exc(file=sys.stdout)
                    print('-'*60)
                    if rdy is running:
                        rdy.unrun(INTERFACES)
                        running = None
                        # Notify everyone else
                        send_to_all(CLIENTS, {'id': RUNAPPLICATION, 'client': 0, 'fid': 0, 'interfaces': 0}, rdy)
                    rdy.close()
                    CLIENTS.remove(rdy)
                    WATCHED.remove(rdy)
    for c in CLIENTS:
        print("closing client: ", c.id)
        if c is running:
            c.unrun(INTERFACES)
        c.close()
    wss.close()
    print("exporter exit")


def main():
    # Initialize supported netem delay distributions
    PROFILE_DELAY_DISTRIBUTION['option'] = ['', 'uniform'] + [os.path.splitext(os.path.basename(p))[0] for p in glob.glob('/usr/lib/tc/*.dist')]

    exporter()


if __name__ == '__main__':
    main()
