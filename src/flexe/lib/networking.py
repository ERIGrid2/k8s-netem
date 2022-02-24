'''Flexe network library

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

@author: Matias Elo <matias.elo@vtt.fi>
@author: Markku Savela <markku.savela@vtt.fi>
@author: Kimmo Ahola <kimmo.ahola@vtt.fi>
'''

import os
import fcntl
import socket
import struct
import errno
import json


def set_default(obj):
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, tuple) and hasattr(obj, '_asdict'):
        return obj._asdict()
    return obj


class Network (object):
    """ Class for managing and using TCP sockets. """

    def __init__(self, socktype=socket.SOCK_STREAM, sct=None):
        """ Initialize internal class variables. """
        self._socket = sct
        self._type = socktype
        # self.recv_buf = ''
        self.recv_buf = b''
        self.size = None

    def __del__(self):
        """ Free used resources. """
        if self._socket is not None:
            self._socket.close()

    def socket(self):
        """ Return the raw socket.
        """
        return self._socket

    def fileno(self):
        """ Return the fileno of the socket.
        """
        return self._socket.fileno()

    def getpeername(self):
        """ Return peer address
        """
        addr = self._socket.getpeername()
        if addr[0].startswith("::ffff:"):
            addr = (addr[0][7:],) + addr[1:]
        return addr

    def getsockname(self):
        """ Return peer address
        """
        addr = self._socket.getsockname()
        if addr[0].startswith("::ffff:"):
            addr = (addr[0][7:],) + addr[1:]
        return addr

    def close(self):
        """ Close the socket
        """
        sock = self._socket
        self._socket = None
        if sock:
            sock.close()

    def createServerSocket(self, addr):
        """ Creates a server socket.

            Args:
                addr: Address and port to be used.
        """
        self._socket = socket.socket(socket.AF_INET6, self._type)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind(addr)
            if self._type == socket.SOCK_STREAM:
                self._socket.listen(socket.SOMAXCONN)
            return
        except socket.error:
            self._socket.close()
            self._socket = None
            raise

    def createClientSocket(self, address, port=None):
        """ Creates a client socket.

            Args:
                address: Target domain name or raw address.
                port: Server listening port

            Exceptions:

                ValueError: if address tuple does not have 2 (ipv4) or
                4 (ipv6) members.

                socket.error: if connection cannot be established for
                given address.
        """
        if port is not None:
            # Get possible addresses
            addrOptions = socket.getaddrinfo(address, port, socket.AF_UNSPEC,
                                             self._type)
        elif len(address) == 2:
            addrOptions = [(socket.AF_INET, self._type, 0, address[0], address)]
        elif len(address) == 4:
            addrOptions = [(socket.AF_INET6, self._type, 0, address[0], address)]
        else:
            raise ValueError("Invalid socket address {}".format(address))

        # Try to connect
        for (fam, type, proto, cname, addr) in addrOptions:
            try:
                self._socket = socket.socket(fam, type, proto)
                try:
                    self._socket.connect(addr)
                    return
                except socket.error:
                    self._socket.close()
            except socket.error:
                pass
            self._socket = None
        raise socket.error("No successful connection with address {}".format(address))

    # REVISIT: send/rcve as written now do not work with DATAGRAM
    # sockets (and such would not need the message framing either).

    def _send(self, msg):
        """Send raw data to socket.

        Exceptions:

            socket.error: if send reports an error

        """
        total = 0
        while total < len(msg):
            sent = self._socket.send(msg[total:], socket.MSG_WAITALL)
            if sent == 0:
                raise socket.error("dead send socket")
            total += sent

    def _rcve(self, size):
        """Receive raw data from the socket.

        Exceptions:

            socket.error: if recv reports an error
        """
        msg = ''
        while len(msg) < size:
            chunk = self._socket.recv(size-len(msg))
            if chunk == '':
                raise socket.error("dead rcve socket")
            msg += chunk
        return msg

    def _send_frame(self, msg, opcode=1):
        # First proto websocket framing subset:
        # fin   : 1 (no fragmenting)
        # rsv1  : 0
        # rsv2  : 0
        # rsv3  : 0
        # opcode: opcode
        # mask  : 0 (no masking yet)

        packed_hdr = ((1 << 7) | opcode).to_bytes(1, "big")
        length = len(msg)
        if length <= 125:
            packed_hdr = b''.join([packed_hdr, length.to_bytes(1, "big")])
        elif length < (1 << 16):
            packed_hdr = b''.join([packed_hdr, (126).to_bytes(1, "big"), length.to_bytes(2, "big")])
        elif length < (1 << 63):
            packed_hdr = b''.join([packed_hdr, (127).to_bytes(1, "big"), length.to_bytes(8, "big")])
        else:
            raise socket.error("message too long: {}".format(length))
        packet_data = b''.join([packed_hdr, msg.encode('utf-8')])
        self._send(packet_data)

    def send(self, obj):
        """Send object to the socket.

        Args:
            obj: Any Python object which can be serialized by json
            module.

        """
        if self._socket:
            self._send_frame(json.dumps(obj, default=set_default))

    def send_async(self):
        """Send data asynchronously.
        TBD.

        The asynchronous send should be called when there is pending
        data to be output and the socket indicates it is ready for
        more output.

        Return True, if all pending data was flushed out.

        Return False, if not all data was sent.
        """

        # TODO
        pass

    def _length(self):
        # fin   : 1 (no fragmenting)
        # rsv1  : 0
        # rsv2  : 0
        # rsv3  : 0
        # opcode: 1 (text frame always)
        # mask  : 0 (no masking yet)
        d = self._rcve(2)
        length = d[1] & 0x7f
        if length == 126:
            d = self._rcve(2)
            length = struct.unpack('!H', d)[0]
        elif length == 127:
            d = self._rcve(8)
            length = struct.unpack('!Q', d)[0]
        return length

    def rcve(self):
        """Receive object from the socket.

        Returns the received Python object (which has been
        un-serialized by json module).
        """
        size = self._length()
        data = self._rcve(size)
        frmt = "!{}s".format(size)
        msg = struct.unpack(frmt, data)

        return json.loads(msg[0])

    def _check_rcve_buf(self):
        # Proto websocket framing, assuming
        # fin   : 1 (no fragmenting)
        # rsv1  : 0
        # rsv2  : 0
        # rsv3  : 0
        # opcode: 1 (text frame always)
        # mask  : 0 (no masking yet)
        if self.size is None:
            if len(self.recv_buf) < 2:
                return None
            self.hdrsize = 2
            self.opcode = self.recv_buf[0] & 0x0f
            if self.opcode == 0x8:
                raise EOFError
            mask = self.recv_buf[1] & 0x80
            length = self.recv_buf[1] & 0x7f
            if length == 126:
                if len(self.recv_buf) < 4:
                    return None
                length = struct.unpack_from('!H', self.recv_buf[2:])[0]
                self.hdrsize = 4
            elif length == 127:
                if len(self.recv_buf) < 10:
                    return None
                length = struct.unpack_from('!Q', self.recv_buf[2:])[0]
                self.hdrsize = 10
            if mask:
                if len(self.recv_buf) < self.hdrsize + 4:
                    return None
                self.mask = [c for c in self.recv_buf[self.hdrsize:self.hdrsize+4]]
                self.hdrsize += 4
            else:
                self.mask = None
            self.size = length
        if len(self.recv_buf) < self.hdrsize+self.size:
            return None
        frmt = "!{}s".format(self.size)
        data = struct.unpack_from(frmt, self.recv_buf[self.hdrsize:])[0]
        self.recv_buf = self.recv_buf[self.hdrsize+self.size:]
        if self.mask is not None:
            data = ''.join(chr(data[i] ^ self.mask[i & 3]) for i in range(len(data)))
        self.size = None
        if self.opcode == 0x9:
            # Was ping, send pong
            self._send_frame(data, opcode=0xa)
            return None
        elif self.opcode != 1:
            # Accept only text frames for now, fragments not supported...
            return None
        return json.loads(data)

    def rcve_async(self, do_read=True):
        """Receive object from the socket asynchronously.

        The asynchronous receive is intended to be used in connection
        with select/poll. This should only be called when there is an
        indication, that more data on the socket is available.

        Returns None, when object is not yet available (not enough
        data received). Otherwise, returns the received Python object
        un-serialized by json module.
        """
        obj = self._check_rcve_buf()
        if not do_read or obj is not None:
            return obj

        eof = False
        try:
            chunk = self._socket.recv(4096, socket.MSG_DONTWAIT)
            # Cannot used anymore in Python3, now recv returns bytes, not string
            self.recv_buf = b''.join([self.recv_buf, chunk])
            eof = (len(chunk) == 0)
        except socket.error as err:
            # print(f'sock error {err}: {msg}')
            if err.errno == errno.EAGAIN or err.errno == errno.EWOULDBLOCK or err.errno == errno.EINTR:
                # NOTE: This is not EOF condition!!!
                chunk = ''
            else:
                raise
        obj = self._check_rcve_buf()
        if obj is None and eof:
            raise EOFError
        return obj

    def query(self, obj):
        """ Send object and receive the reply.
        """
        self.send(obj)
        return self.rcve()

    def waitIncoming(self):
        """ Wait for incoming client connections.
        """
        return self._socket.accept()


def setPort(address, port):
    """
    Return address tuple with modified port
    """
    (a, p, x, y) = address
    return (a, port, x, y)


def printable(address):
    """
    Return address as a string formatted as "address#port".
    """
    astr = address[0]
    # Crude solution to return IPv4 mapped address as plain IPv4
    if astr.startswith("::ffff:"):
        astr = astr[7:]
    return astr + '#' + str(address[1])


def set_nonblock(sock):
    flags = fcntl.fcntl(sock, fcntl.F_GETFL) | os.O_NONBLOCK
    fcntl.fcntl(sock, fcntl.F_SETFL, flags)
