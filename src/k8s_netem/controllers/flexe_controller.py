"""
Developed by: Kimmo Ahola <Kimmo.Ahola(at)vtt.fi>

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
"""

import websocket
import _thread
import time
import json
import requests
import sys
import os
from requests.auth import HTTPBasicAuth
import queue
import signal
import inotify.adapters
import base64
import argparse
import logging
from logging.handlers import RotatingFileHandler
from logging import handlers

ctrl = None
DEFAULT_INTERFACE="eth0"

def on_message(ws, message):
    """
        Handling the message received from WebSocket
    """
    ctrl.logger.debug("### Websocket message received: {} ###".format(message))
    ctrl.parse_received_message(message)

def on_error(ws, error):
    """
        Handling the WebSocket error message
    """
    ctrl.logger.error("### Websocket received error: {} ###".format(error))

def on_close(ws, close_status_code, close_msg):
    """
        Handling when WebSocket connection is closed
    """ 
    ctrl.logger.debug("### Websocket closed ###")

def on_open(ws):
    """
        Handling when WebSocket connection is opened
    """
    ctrl.logger.debug("### Websocket connection open succeed! ###")
    ctrl.opened = 1
    ctrl.ws = ws

class ControllerClass():
    """
        Class which handles the controlling of Flexe Emulator
    """
    def __init__(self):
        """
            Initialise the variables and parse the command line parameters.
        """
        self.profiles = []
        self.filterid = 1
        self.packing = ""
        self.q = queue.Queue()
        self.opened = 0
        self.running = False
        self.flowcol = {}
        self.onemask = ""
        self.nullmask = ""
        self.ws = None
        self.logger = None

        parser = argparse.ArgumentParser(
            'This program watches the configuration file for changes and communicates with VTT Flexe Netem.')
        parser.add_argument('--configfile', 
            help="Configuration file", 
            type=str, 
            required=True)
        parser.add_argument('--flexehost', 
            help='Flexe Netem host name / ip address',
            default="127.0.0.1", type=str)
        parser.add_argument('--restAPIport', 
            help='Flexe Netem API port.',
            default=8080, type=int)
        parser.add_argument('--wsAPIport', 
            help='Flexe Netem Websocket API port',
            default=8888, type=int)
        parser.add_argument('--log_dir', help='Directory to store log files.',
            default='/tmp', type=str)
        parser.add_argument('--log_to_file', help='Enable logging to a file.',
            action='store_true')
        parser.add_argument('--log_to_screen', help='Enable logging to the screen.',
            action='store_true')

        self.args = parser.parse_args()
        self.initialize_logging()
        self.logger.info("Initialised logging")

    def initialize_logging(self):
        """
           Initialize logging
        """
        self.logger = logging.getLogger('Controller')
        self.log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        if self.args.log_to_file or self.args.log_to_screen:
            self.logger.setLevel(logging.DEBUG)
            if self.args.log_to_file:
                log_file_path = os.path.join(
                    self.args.log_dir, 'controller-{}.log'.format(
                        datetime.datetime.now().strftime('%Y%m%d_%H%M%S')))
                fh = handlers.RotatingFileHandler(log_file_path, maxBytes=0, backupCount=0)
                fh.setFormatter(self.log_format)
                self.logger.addHandler(fh)
            if self.args.log_to_screen:
                ch = logging.StreamHandler(sys.stdout)
                ch.setFormatter(self.log_format)
                self.logger.addHandler(ch)
        else: # Log only errors to to screen
            self.logger.setLevel(logging.CRITICAL)
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(self.log_format)
            self.logger.addHandler(ch)

    def sigint_handler(self, signum, frame):
        """
           Handle the CTRL-C (SIGINT) signal
        """
        msg = "Ctrl-c was pressed. Do you really want to exit? y/n "
        #print(msg, end="", flush=True) # python3
        res = input(msg).rstrip()
        if res == 'y':
            print("")
            self.ws.close()
            time.sleep(1)
            exit(1)
        else:
            print("", end="\r", flush=True)
            print(" " * len(msg), end="", flush=True) # clear the printed line
            print("    ", end="\r", flush=True)

    def parse_received_message(self, message):
        """
            Parses the received message from Flexe Emulator

            Mainly check the id of the message and act accordingly
        """
        data_received = json.loads(message)
        id_of_message = data_received.get("id", None)

        if id_of_message == None:
            self.logger.error("Format not recognized!")
            return

        self.logger.debug ("Received this message id: {}".format(id_of_message))
        if id_of_message == "GetPacking":
            self.packing = data_received.get("result", None)
            self.handle_packing_message(self.packing)
        elif id_of_message == "NewInterface":
            self.interfaces = data_received.get("result", None)
        elif id_of_message == data_received.get("filters"):
            if "fid" in data_received and data_received.get("fid") != self.filterid:
                self.filterid = int(data_received.get("fid", None))
                self.logger.debug("Now filterid == {}".format(self.filterid))
        elif id_of_message == "filter":
            if "fid" in data_received and data_received.get("fid") == self.filterid:
                cnts = data_received.get("cnt")
                for cnt in cnts:
                    # Format: [filter_id, inbound_packets, outbound_packets, timestamp]
                    filter_id, inbound_pkts, outbound_pkts, timestamp = cnt
                    if filter_id == 0 and inbound_pkts == 0 and outbound_pkts == 0:
                        self.logger.debug("Hearbeat message")

        elif id_of_message == "RunApplication":
            self.logger.info("Received RunApplication -> forget it")
        elif id_of_message == "ProfileTemplate":
            self.logger.info("Received ProfileTemplate -> forget it")

    def handle_packing_message(self, msg):
        """
            Handle the received GetPacking message from Flexe Emulator
        """
        i = 0
        index = 0
        for pack in msg:
            if len(pack) == 4:
                self.flowcol[pack[2]] = [i, index, pack[0]]
                i += 1
                index += int(pack[0])

        ff = chr(int(b'0xff',16))
        nul = chr(int(b'0x00',16))
        self.onemask = ff.ljust(index, ff)
        self.nullmask = nul.ljust(index, nul)

        self.logger.debug("Self.flowcol: {}".format(self.flowcol))

    def get_profiles(self):
        """
            Fetch the profiles from Flexe Emulator REST API
        """
        self.logger.info("Fetch all the known profiles from Flexe...")

        url_server = "http://{}:{}/flexe/profiles".format(self.args.flexehost, self.args.restAPIport)
        r = requests.get(url_server, auth=HTTPBasicAuth('flexe', ''))

        if r.status_code != 200:
            self.logger.error("Get profiles failed with status code {} -> bailing out".format(r.status_code))
            return
        else:
            if r.json() is not None:
                profiles = r.json().get("result")
                self.logger.info("Profiles: {}".format(profiles))
            else:
                profiles = []
        
        # Now get more information from all profiles
        for profile in profiles:
            url = "{}/{}".format(url_server, profile)
            r = requests.get(url, auth=HTTPBasicAuth('flexe', ''))
            if r.status_code != 200:
                self.logger.debug("Getting more information about the profile failed with status code {} -> bailing out".format(r.status_code))
                return
            else:
                self.profiles.append({profile: r.json()})
        
        self.logger.debug("Now all profiles have fetched and data in: {}".format(self.profiles))

    def ws_thread(self):
        """
            Thread handling the WebSocket communication 
        """
        websocket.enableTrace(False)
        url_ws = "ws://{}:{}/".format(self.args.flexehost, self.args.wsAPIport)
        ws = websocket.WebSocketApp(url_ws,
                                    on_open=on_open,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close)
        ws.run_forever()

    def init_ws_thread(self):
        """
            Initialise the WebSocket thread
        """
        _thread.start_new_thread(self.ws_thread, ())

    def configure(self, configuration):
        """
            Parse the configuration from the file data
        """
        profile_infos = {}
        filters = []
        profiles = []
        send_filters = True
        profile_info = None

        # configuration is list of dicts.
        for conf in configuration:
            # Check if configuration has profile which we can use
            requested_profile = conf.get("profile", None)
            self.logger.debug("Requested profile: {}".format(requested_profile))

            # If one of the requested_profile == "", that means stop Flexe NetEm
            if requested_profile is not None and len(requested_profile) > 0:
                for prof in self.profiles:
                    key = list(prof.keys())[0]
                    if key == requested_profile:
                        profile_info = prof.get(key)
                
                if profile_info is None:
                    self.logger.error("Profile unknown -> don't do anything")
                    return

                profiles.append(["", requested_profile])
                profile_infos[requested_profile] = {"segments": [profile_info], "run": {"start":0, "end": 1}}

                # His assumes that fwmark is the only filtering parameter
                # For this specific case (EriGrid2), this is the case.
                if "fwmark" in self.flowcol:
                    index = self.flowcol.get("fwmark")[1]
                    size = self.flowcol.get("fwmark")[2]
                else:
                    self.logger.error("Packing not yet received!")
                    return

                fwmark = conf.get("fwmark")
                i = size
                value = ''
                while fwmark and i:
                    i-=1
                    value = chr(fwmark & 0xff) + value
                    fwmark = fwmark >> 8

                key = str(self.nullmask[:index]) + str(value) + str(self.nullmask[index+size:])
                mask = str(self.nullmask[:index]) + str(chr(255) + chr(255)) + chr(255) + chr(255) + str(self.nullmask[index+size:])

                base64_key = base64.b64encode(key.encode("raw_unicode_escape")).decode("utf-8")
                base64_mask = base64.b64encode(mask.encode("raw_unicode_escape")).decode("utf-8")

                interface = ""
                if "interface" in conf:
                    interface = conf.get("interface")
                else:
                    interface = DEFAULT_INTERFACE

                # Only set this netem filter to interface "interface"
                for inf in self.interfaces:
                    name, value2, value = inf
                    if name == interface:
                        filters.append([base64_key, base64_mask, 0, value2, True])
            else:
                # This is case when configuration file does not include value for profile
                # This means that current tc configuration should be stopped
                send_filters = False
                profile_infos = {}
                profiles = None
                break

        if send_filters:
            self.filterid += 1
            # Now send the first the filter information to Flexe
            msg = {
                "id": "SetFilters",
                "user": "flexe",
                "fid": self.filterid,
                "filters": filters,
            }

            message = json.dumps(msg)
            
            self.q.put({"name": "send", "data": message})

        # Then start the application
        msg = {
            "id": "RunApplication",
            "user": "flexe",
            "fid": self.filterid,
            "profiles": profiles,
            "profile_data": profile_infos
        }

        message = json.dumps(msg)
        self.q.put({"name": "send", "data": message})

    def handle_configuration_file(self, filename):
        """
            Open the configuration file and read it. Then parse the information using configure method.
        """
        with open(filename, 'r') as f:
            last_config = json.load(f)
            self.configure(last_config)

    def main(self):
        """
           Like name implies, the master method of this class
        """ 
        signal.signal(signal.SIGINT, self.sigint_handler)

        # Now handle Websocket stuff
        while self.opened != 1:
           self.logger.info("Waiting Websocket to be opened...")
           time.sleep(1)

        message = json.dumps({"id": "GetPacking"})
        self.ws.send(message)

        i = inotify.adapters.Inotify()

        # Adding file modification in this directory
        fullpath = os.path.abspath(self.args.configfile)
        watch_path, watch_filename = os.path.split(fullpath)
        i.add_watch(watch_path)

        self.logger.debug("Now waiting every 1s if {} is changed or we have something to be send to WebSocket".format(watch_filename))
        last_hash = None

        while 1:
            try:
                for event in i.event_gen(yield_nones=False, timeout_s=1):
                    (_, type_names, path, filename) = event

                    if watch_filename != filename:
                        continue

                    if 'IN_MODIFY' not in type_names:
                        continue

                    with open(fullpath, 'r') as f:
                        contents = f.read()
                        new_hash = hash(contents)
                    
                    if new_hash != last_hash:
                        self.logger.info("Configuration file changed -> handle modifications")
                        self.handle_configuration_file(self.args.configfile)
                        last_hash = new_hash
                
                # Now handle Websocket stuff
                item = self.q.get(timeout=1)

                if item.get("name") == "stop":
                    self.logger.info("Stop command received -> stopping everything...")
                    self.ws.close()
                    i.remove_watch(path)
                    exit(1)
                elif item.get("name") == "send":
                    self.logger.debug("Now send to websocket: {}".format(item.get("data")))
                    self.ws.send(item.get("data"))
            except queue.Empty:
                continue

if __name__ == "__main__":
    # Create main class
    ctrl = ControllerClass()

    # First check what profiles can be found from Flexe Netem
    ctrl.get_profiles()

    # Initialise Websocket communication towards packet.py
    ctrl.init_ws_thread()

    # Start main loop
    ctrl.main()
