'''FLEXE Server

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

import os
import tornado.ioloop
import tornado.web
import tornado.httpserver

import argparse
import logging
import logging.handlers
import re
import glob
import socket
import base64
import flexe.lib.configuration as conf
import flexe.lib.account as account
import ssl

common_name = None


class ServiceError(Exception):
    pass


FILENAME = re.compile(r'^[a-zA-Z0-9][-a-zA-Z0-9_\.]*$')
# Allow ':' in host part to cover IPv6 addresses
FILEHOST = re.compile(r'^[a-zA-Z0-9:][-a-zA-Z0-9_\.:]*$')

FILESETS = ('profiles', 'applications')


def authenticate(f):
    """Require HTTP Basic Authentication from the GET/POST/...
    """
    def wrap(self, *args, **kwargs):
        # Require that request has the correct authentication header
        # and pick up the user/password
        auth = self.request.headers.get('Authorization')
        if auth and auth.startswith('Basic '):
            self.user, _, password = base64.b64decode(auth[6:]).decode("utf-8").partition(':')

            # WARNING: check_user takes up lots of cpu time
            if account.check_user(self.user, password):
                try:
                    f(self, *args, **kwargs)
                except ServiceError as e:
                    _json_error(self, str(e))
                return

        # Authentication required
        self.set_status(401)
        self.set_header('WWW-Authenticate', 'Basic realm="FLEXE"')
        self.finish()

    return wrap


# Note: self must be explicitly passed
def log_message(self, format, *args):
    logging.info("%s - - [%s] %s" %
                 (self.client_address[0],
                  self.log_date_time_string(),
                  format % args))


# Note: self must be explicitly passed
def _json_reply(self, data):
    self.set_header('Content-type', 'application/json')
    self.write(data)


# Note: self must be explicitly passed
def _json_error(self, msg, id=None):
    data = {'message': msg}
    if id is not None:
        data['id'] = id
    _json_reply(self, data)


class SetPassword(tornado.web.RequestHandler):

    @authenticate
    def post(self, id, *args):
        params = tornado.escape.json_decode(self.request.body)
        if params['newpass1'] != params['newpass2']:
            raise ServiceError("New password mismatch")
        if not account.password(self.user, params['oldpass'], params['newpass1']):
            raise ServiceError("Incorrect old password")
        _json_reply(self, {'id': id, 'user': self.user, 'message': 'Password changed'})


class AddUser(tornado.web.RequestHandler):

    @authenticate
    def post(self, id, *args):
        if self.user != account.ADMIN:
            raise ServiceError("Adding users only allowed for admin account")
        params = tornado.escape.json_decode(self.request.body)
        if params['newpass1'] != params['newpass2']:
            raise ServiceError("New password mismatch")
        if not account.add_user(params['username'], params['newpass1']):
            raise ServiceError("User '{}' already exists".format(params['username']))
        _json_reply(self, {'id': id, 'user': self.user, 'message': "User '{}' created".format(params['username'])})


class GetHostByAddr(tornado.web.RequestHandler):

    @authenticate
    def get(self, id, path):
        result = {}
        reply = {'id': id, 'result': result}
        for ip in path.split('/'):
            try:
                result[ip] = socket.gethostbyaddr(ip)
            except Exception:
                result[ip] = None
        _json_reply(self, reply)


class Switches(tornado.web.RequestHandler):
    @authenticate
    def get(self, id):
        # Provide a dummy reply for now...
        reply = {
            'id': id,
            'user': self.user,
            'result': {'local': ('127.0.0.1', 8888)}
        }
        _json_reply(self, reply)


class FlexeHandler(tornado.web.RequestHandler):

    def _file_name_in(self, dir, name, client=False):
        name, _, user = name.rpartition('@')
        if not name:
            name = user
            user = self.user
        elif client:
            # Ignore original user, return client always
            user = self.user

        if not FILENAME.match(name):
            raise ServiceError("name '{}' contains invalid characters".format(name))
        if user and not FILEHOST.match(user):
            raise ServiceError("user '{}' contains invalid characters".format(user))
        return './' + dir + '/' + name + '@' + user, name, user

    def _file_name_out(self, path):
        path = path.rpartition('/')[2]  # Get bare filename
        name, _, host = path.rpartition('@')
        if not name:
            return host
        if host == self.user:
            return name
        return path

    @authenticate
    def delete(self, dir, name):
        if name is None or name == '/':
            raise ServiceError("DELETE target not given: {}".format(self.request.path))

        try:
            name = name[1:]  # strip leading '/'
            path, name, host = self._file_name_in(dir, name)
            # Use original input host
            if self.user != host:
                raise ServiceError("Cannot remove '{}' -- not owned by you '{}'".format(name, self.user))
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isfile(os.path.dirname(path) + "/" + name):
                raise ServiceError("Cannot remove permanent file '{}'".format(name))
            else:
                raise ServiceError("'{}' does not exist".format(name))

            _json_reply(self, {'id': dir,
                               'user': self.user,
                               'message': "Removed '" + self._file_name_out(path) + "'"})
        except Exception as e:
            raise ServiceError("Delete '{}' failed: {}".format(name, str(e)))

    @authenticate
    def post(self, dir, name):
        if name is None or name == '/':
            raise ServiceError("POST target not given: {}".format(self.request.path))

        name = name[1:]
        path, _, _ = self._file_name_in(dir, name, client=True)
        try:
            directory = os.path.dirname(path)
            if not os.path.exists(directory):
                os.makedirs(directory)
            with open(path, "w") as f:
                f.write(self.request.body.decode('UTF-8'))
        except Exception as e:
            raise ServiceError("failed saving '{}': {}".format(path, e))
        _json_reply(self, {'id': dir, 'user': self.user, 'message': "Saved '" + self._file_name_out(path) + "'"})

    @authenticate
    def get(self, dir, name):
        if name is None or name == '/':
            # Empty name part is a request for list of files.
            _json_reply(self,
                        {'id': dir,
                         'user': self.user,
                         'result': list(set([self._file_name_out(x.rpartition('/')[2]) for x in glob.glob('./' + dir + '/*')]))})
        else:
            name = name[1:]  # name starts always with '/', remove it
            path, name, host = self._file_name_in(dir, name)
            try:
                # If a file "name@client" exist, return that. Otherwise
                # try opening plain "name" (allows saved view that can be
                # loaded by any client, but not modifified)
                if not os.path.isfile(path):
                    path = dir + '/' + name

                with open(path, "r") as f:
                    # This assumes saved data is a JSON string
                    self.set_header('Content-type', 'application/json')
                    self.write(f.read())
            except Exception as e:
                raise ServiceError("Failed reading file '{}': {}".format(path, str(e)))


def start(args):
    app = tornado.web.Application([
        (r"/flexe/(profiles|applications)(/.*)?", FlexeHandler),
        (r"/flexe/(setPassword)(/.*)?", SetPassword),
        (r"/flexe/(addUser)(/.*)?", AddUser),
        (r"/flexe/(switches)", Switches),
        (r"/(GetHostByAddr)/(.*)", GetHostByAddr)
    ])

    if args.ssl is not None:
        if not conf._CF['client_key'] or not conf._CF['client_crt'] or not conf._CF['root_ca']:
            print("SSL Server option requires configured key/crt/root_ca")
            return
        server = tornado.httpserver.HTTPServer(app, dict(
            keyfile=conf.path(conf._CF['client_key']),
            certfile=conf.path(conf._CF['client_crt']),
            server_side=True,
            cert_reqs=ssl.CERT_OPTIONAL if args.peer is None else ssl.CERT_REQUIRED,
            ca_certs=conf.path(conf._CF['root_ca'])))
    else:
        server = app

    server.listen(args.port, address=args.addr)
    tornado.ioloop.IOLoop.instance().start()


def address_and_port(arg):
    ap = arg.rsplit(':', 1)
    if len(ap) == 2:
        return (ap[0], int(ap[1]))
    return (ap[0], 8888)


def main():
    parser = argparse.ArgumentParser(description='FLEXE Controller',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # --ssl enables secure socket
    # --peer is ignored unless ssl is set
    #    --peer not specified => peer cert not verified nor required
    #    --peer=CN => verify peer cert and require commonName == CN
    #    --peer= => CN=='', verify peer cert, don't check commonName
    parser.add_argument('--ssl', help="Use HTTPS", action='store_const', const=True)
    parser.add_argument('--peer', nargs='?', const='FLEXE_CLIENT',
                        help="With HTTPS require peer cert. Verify commonName, unless COMMON NAME is empty string",
                        metavar='COMMON NAME')
    parser.add_argument('--addr', help="Listening address", default=conf._CF['listen_addr'])
    parser.add_argument('--port', help="Listening port", type=int, default=conf._CF['listen_port'])
    parser.add_argument('--debug', help="Log into console", action='store_const', const=True)
    parser.add_argument('--packet', help="List of the packet engine addresses as <host:port> pairs (web socket)",
                        nargs='*', type=address_and_port, default=[('127.0.0.1', 8888)])

    args = parser.parse_args()

    if args.debug:
        logfile = 'console'
        logging.basicConfig(level=logging.DEBUG)
    else:
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logfile = os.path.join(conf.path(conf._CF['log_dir']), 'server.log')
        hdlr = logging.handlers.TimedRotatingFileHandler(
            logfile,
            when='midnight', backupCount=7)
        logger.addHandler(hdlr)

    if args.ssl:
        report = "Listening HTTPS on {}#{}".format(args.addr, args.port)
        # REVISIT: peer cert checking not working now with tornado?
        if args.peer is None:
            report += " -- peer certificate not required"
        elif args.peer:
            report += " -- peer certificate required with CN='{}'".format(args.peer)
        else:
            report += " -- peer certificate required, CN not checked"
    else:
        report = "Listening HTTP on {}#{}".format(args.addr, args.port)
        if args.peer:
            report += " -- ignoring '-peer={}' checking"
    report += ", logs into " + logfile
    logging.info(report)

    print(report)

    start(args)


if __name__ == '__main__':
    main()
