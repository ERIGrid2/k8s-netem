'''Flexe controller

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

@author Kimmo Ahola <Kimmo.Ahola(at)vtt.fi>
'''

import websocket
import time
import json
import requests
from requests.auth import HTTPBasicAuth
import queue
import base64
import threading

from typing import Dict
from typing import AnyStr
from typing import List

from k8s_netem.controller import Controller
from k8s_netem.profile import Profile

FLEXE_USER = 'flexe'
FLEXE_PASSWORD = ''
FLEXE_WS_URL = 'ws://localhost:8888/'
FLEXE_API_URL = 'http://localhost:8080/flexe'


# Main FlexeController class
class FlexeController(Controller):
    type = 'Flexe'

    def __init__(self, intf: str):
        '''Initialise the variables and parse the command line parameters.'''

        super().__init__(intf)

        self.flexe_profiles: list = []
        self.filterid = 1
        self.packing = ''
        self.queue: queue.Queue = queue.Queue()
        self.opened = 0
        self.running = False
        self.flowcol: dict = {}
        self.onemask = ''
        self.nullmask = ''
        self.ws: websocket.WebSocketApp = None
        self.ws_thread_id = None
        self.main_thread_id = None
        self.interfaces = None

        # Initialise Websocket communication towards Flexe Emulator
        self.ws_thread_id = threading.Thread(target=self.ws_thread)
        self.ws_thread_id.daemon = True
        self.ws_thread_id.start()

        # Now wait before Websocket is opened
        while self.opened != 1:
            self.logger.info('Waiting Websocket to be opened...')
            time.sleep(1)

        self.logger.info('Now Websocket is open.')

        # The initial information from the Flexe Emulator Websocket interface
        # can be fetched with the code below. That will return the information
        # what kind of parameters Flexe Emulator accepts.
        message = json.dumps({'id': 'GetPacking'})
        self.ws.send(message)
        self.logger.info('Sent initial message to Flexe server')

        self.main_thread_id = threading.Thread(target=self.main_thread)
        self.main_thread_id.daemon = True
        self.main_thread_id.start()

        # Fetch all already known profiles from Flexe Emulator REST API
        # self.get_profiles()

    def on_message(self, message):
        '''Handling the message received from WebSocket'''

        self.logger.debug('Websocket message received: %s', message)
        self.parse_received_message(message)

    def on_error(self, error):
        '''Handling the WebSocket error message'''

        self.logger.error('Websocket received error: %s', error)

    def on_close(self, close_status_code, close_msg):
        '''Handling when WebSocket connection is closed'''

        self.logger.debug('Websocket closed')

    def on_open(self):
        '''Handling when WebSocket connection is opened'''

        self.logger.debug('Websocket connection open succeed')
        self.opened = 1

    def main_thread(self):
        while True:
            try:
                item = self.queue.get(timeout=1)

                if item.get('name') == 'stop':
                    self.logger.info('Stop command received -> stopping everything...')
                    self.ws.close()
                    # i.remove_watch(path)  # seems broken?
                    exit(1)
                elif item.get('name') == 'send':
                    self.logger.debug('Now send to websocket: %s', item.get('data'))
                    self.ws.send(item.get('data'))
            except queue.Empty:
                continue

    def ws_thread(self):
        '''Thread handling the WebSocket communication'''

        websocket.enableTrace(False)

        self.ws = websocket.WebSocketApp(FLEXE_WS_URL,
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)
        self.ws.run_forever()

    def deinit(self):
        self.logger.info('deinit')

        if self.ws_thread_id.is_alive():
            self.ws_thread_id.join(0.0)

        if self.main_thread_id.is_alive():
            self.main_thread_id.join(0.0)

    def add_profile(self, profile: Profile):
        self.logger.info('Add profile: %s', profile)
        self.logger.info('  with parameters: %s', profile.parameters)
        super().add_profile(profile)

        self.update_flexe(profile, "add")

    def remove_profile(self, profile: Profile):
        self.logger.info('Remove profile: %s', profile)
        super().remove_profile(profile)

        self.update_flexe(profile, "delete")

    def update_profile(self, profile: Profile):
        self.logger.info('Update profile: %s', profile)
        super().update_profile(profile)

        self.update_flexe(profile, "update")

    def parse_segments(self, profiles: Dict, segments: List) -> Dict:
        segment_dict = {}
        segment_dict['segments'] = []

        # Try to find first how many segments we have
        end = len(profiles)
        segment_dict['run'] = {'start': 0, 'end': end+1}

        for segment in segments:
            if segment and "repeat" in segment:
                repeat = segment.get("repeat")
                segment_dict['run']['repeat'] = repeat
            else:
                segment_dict['run']['repeat'] = False

        # Then find add the profile parameters to segment information
        for prof in profiles:
            segment_dict['segments'].append(profiles.get(prof))

        return segment_dict

    def handle_filter_creation(self, profile: Profile) -> Dict:
        filters = []

        # This assumes that fwmark is the only filtering parameter
        # For this specific case (EriGrid2), this is the case.
        if 'fwmark' in self.flowcol:
            index = self.flowcol.get('fwmark')[1]
            size = self.flowcol.get('fwmark')[2]
        else:
            self.logger.error('Packing not yet received!')
            return {}

        fwmark = profile.mark

        i = size
        value = ''
        while fwmark and i:
            i -= 1
            value = chr(fwmark & 0xff) + value
            fwmark = fwmark >> 8

        key = str(self.nullmask[:index]) + str(value) + str(self.nullmask[index+size:])
        mask = str(self.nullmask[:index]) + str(chr(255) + chr(255)) + chr(255) + chr(255) + str(self.nullmask[index+size:])

        base64_key = base64.b64encode(key.encode('raw_unicode_escape')).decode('utf-8')
        base64_mask = base64.b64encode(mask.encode('raw_unicode_escape')).decode('utf-8')

        if self.interfaces is None:
            return {}

        # Only set this netem filter to interface 'interface'
        for inf in self.interfaces:
            name, value2, value = inf
            if name == self.interface:
                filters.append([base64_key, base64_mask, 0, value2, True])

        self.filterid += 1
        # Now send the first the filter information to Flexe
        msg = {
            'id': 'SetFilters',
            'user': 'flexe',
            'fid': self.filterid,
            'filters': filters,
        }

        return msg

    def handle_run_message_creation(self, profile: Profile) -> Dict:
        profiles = []
        profile_infos = {}
        defined_profiles = {}

        # First parse information about all the profiles
        for parameter in profile.parameters.get('profiles', None):
            profile_name = parameter.get('name', "")
            profile_info = parameter.get('parameters')
            defined_profiles[profile_name] = profile_info

        segments = profile.parameters.get('segments', None)
        segment_info = self.parse_segments(defined_profiles, segments)

        # This assumes that requested_profile is the profile which is used in all the segments.
        # If there are more segments, then only the modification need per segment is needed.
        # Check also that runTime is found in every segment.
        profile_name = ""
        if len(defined_profiles) > 1:
            profile_name = 'segmented_profiles'
        else:
            # Take the first name of profile
            profile_name = list(defined_profiles.keys())[0]

        profiles.append(['', profile_name])

        profile_infos[profile_name] = {
            'segments': segment_info.get('segments', []),
            'run': segment_info.get('run', {'start': 0, 'end': 1})
        }

        msg = {
            'id': 'RunApplication',
            'user': 'flexe',
            'fid': self.filterid,
            'profiles': profiles,
            'profile_data': profile_infos
        }

        return msg

    def update_flexe(self, profile: Profile, mode: AnyStr):
        send_filters = True

        # Handle the runApplication message creation
        run_msg = self.handle_run_message_creation(profile)

        # Check if the egress profile name is empty -> Flexe NetEm will clear the rules.
        # Also there is no need to send the filter message to Flexe NetEm
        profiles = run_msg.get('profiles', None)
        if mode == "delete" or profiles[0][1] == '' or profiles[0][1] is None:
            send_filters = False
            # Flexe NetEm removes all profiles, if dictionary does not include 'profiles' key
            del run_msg['profiles']

        # Handle the filter message part here
        if send_filters:
            filter_msg = {}
            while len(filter_msg) < 1:
                filter_msg = self.handle_filter_creation(profile)
                # If length of filter_msg is zero, there is need to wait a little bit
                # so WebSocket receives needed information from Flexe NetEm
                if len(filter_msg) == 0:
                    time.sleep(1)
                else:
                    message = json.dumps(filter_msg)
                    self.queue.put({'name': 'send', 'data': message})
                    # filter id (fid) should be the same than in filter message
                    run_msg['fid'] = filter_msg.get('fid')

        message = json.dumps(run_msg)
        self.queue.put({'name': 'send', 'data': message})

    def parse_received_message(self, message):
        '''Parses the received message from Flexe Emulator

        Mainly check the id of the message and act accordingly
        '''

        data_received = json.loads(message)
        id_of_message = data_received.get('id', None)

        if id_of_message is None:
            self.logger.error('Format not recognized!')
            return

        self.logger.debug('Received this message id: %s', id_of_message)

        if id_of_message == 'GetPacking':
            self.packing = data_received.get('result', None)
            self.handle_packing_message(self.packing)

        elif id_of_message == 'NewInterface':
            self.interfaces = data_received.get('result', None)

        elif id_of_message == data_received.get('filters'):
            if 'fid' in data_received and data_received.get('fid') != self.filterid:
                self.filterid = int(data_received.get('fid', None))
                self.logger.debug('Now filterid == %d', self.filterid)

        elif id_of_message == 'filter':
            if 'fid' in data_received and data_received.get('fid') == self.filterid:
                cnts = data_received.get('cnt')
                for cnt in cnts:
                    # Format: [filter_id, inbound_packets, outbound_packets, timestamp]
                    filter_id, inbound_pkts, outbound_pkts, timestamp = cnt
                    if filter_id == 0 and inbound_pkts == 0 and outbound_pkts == 0:
                        self.logger.debug('Hearbeat message')

        elif id_of_message == 'RunApplication':
            self.logger.info('Received RunApplication -> forget it')

        elif id_of_message == 'ProfileTemplate':
            self.logger.info('Received ProfileTemplate -> forget it')
        else:
            self.logger.info('Received something else: %s', data_received)

    def handle_packing_message(self, msg: Dict):
        '''Handle the received GetPacking message from Flexe Emulator'''
        i = 0
        index = 0
        for pack in msg:
            if len(pack) == 4:
                self.flowcol[pack[2]] = [i, index, pack[0]]
                i += 1
                index += int(pack[0])

        ff = chr(int(b'0xff', 16))
        nul = chr(int(b'0x00', 16))
        self.onemask = ff.ljust(index, ff)
        self.nullmask = nul.ljust(index, nul)

        self.logger.debug('Self.flowcol: %s', self.flowcol)

    def get_profiles(self):
        '''Fetch the profiles from Flexe Emulator REST API'''

        self.logger.info('Fetch all the known profiles from Flexe...')

        r = requests.get(f'{FLEXE_API_URL}/profiles', auth=HTTPBasicAuth(FLEXE_USER, FLEXE_PASSWORD))
        if r.status_code != 200:
            self.logger.error('Get profiles failed with status code %d -> bailing out', r.status_code)
            return
        else:
            if r.json() is not None:
                profiles = r.json().get('result')
                self.logger.info('Profiles: %s', profiles)
            else:
                profiles = []

        # Now get more information from all profiles at the Flexe server
        for profile in profiles:
            r = requests.get(f'{FLEXE_API_URL}/profiles/{profile}', auth=HTTPBasicAuth(FLEXE_USER, FLEXE_PASSWORD))
            if r.status_code != 200:
                self.logger.debug('Getting more information about the profile failed with status code %d -> bailing out', r.status_code)
                return
            else:
                self.flexe_profiles.append({profile: r.json()})

        self.logger.debug('Now all profiles have fetched and data in: %s', self.flexe_profiles)

    def save_profile(self, profile_data: Dict, name: AnyStr):
        '''Save profile using Flexe Emulator REST API'''

        headers = {
            'Content-Type': 'application/json'
        }

        r = requests.post(f'{FLEXE_API_URL}/profiles/{name}', auth=HTTPBasicAuth(FLEXE_USER, FLEXE_PASSWORD),
                          data=json.dumps(profile_data),
                          headers=headers)

        # Expected reply
        # {'id': 'profiles', 'user': 'userX', 'message': 'Saved name'})
        if r.status_code != 200:
            self.logger.error('Save profiles failed with status code %d -> bailing out', r.status_code)
        else:
            if r.json() is not None:
                message = r.json().get('message')
                self.logger.info('Message: %s', message)
