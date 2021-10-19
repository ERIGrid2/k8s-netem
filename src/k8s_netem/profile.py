import threading
import logging
from typing import List, Dict
from kubernetes import client, watch

from k8s_netem.ipset import IPset
from k8s_netem.filter import MultiIPsetFilter
from k8s_netem.controllers.tc import TrafficController
from k8s_netem.controllers.vtt import VttController
from k8s_netem.match import LabelSelector

class Rule:

    def __init__(self, direction: 'Direction', index: int, spec):
        self.direction: str = direction
        self.index: int = index
        self.spec: dict = spec

        self.threads: List[threading.Thread] = []
        self.ipsets: List[IPset] = []

    def initialize(self):
        self.setup_ipsets()

        logging.info('Initialized rule: %s', self.spec)

    def deinitialize(self):
        for thread in self.threads:
            thread.join(0.0)

        self.ipsets.clear()

    @property
    def filter(self):
        return MultiIPsetFilter(self.ipsets, self.direction.direction == 'ingress', 'and')

    def setup_ipsets(self):
        peers = self.spec.get('from' if self.direction.direction == 'ingress' else 'to')
        if peers:
            self.ipset_peers = IPset(f'{self.direction.direction}-{self.index}-peers', 'hash', 'net')
                
            for p in peers:
                if 'ipBlock' in p:
                    cidr = p['ipBlock']['cidr']

                    self.ipset_peers.add(cidr)

                elif 'namespaceSelector' in p or 'podSelector' in p:
                    thread = threading.Thread(target=self.sync, args=(p,))
                    thread.start()
        
                    self.threads.append(thread)

            self.ipsets.append(self.ipset_peers)

        ports = self.spec.get('ports')
        if ports:
            self.ipset_ports = IPset(f'{self.direction.direction}-{self.index}-ports', 'bitmap', 'port')

            for p in ports:
                port = p.get('port')
                proto = p.get('protocol', 'TCP').lower()

                self.ipset_ports.add(f'{proto}:{port}')

            self.ipsets.append(self.ipset_ports)

    def sync(self, peer):
        logging.info('Started sync thread for %s', peer)

        # We only support podSelectors for now...
        if 'podSelector' not in peer:
            raise NotImplementedError()
        
        w = watch.Watch()
        v1 = client.CoreV1Api()

        selector = LabelSelector(peer['podSelector']).to_labelselector()

        for event in w.stream(v1.list_pod_for_all_namespaces, label_selector=selector):
            pod = event['object']

            logging.info('%s %s/%s (%s)', event['type'].capitalize(), pod.metadata.namespace, pod.metadata.name, pod.status.pod_ip)
            
            if event['type'] in ['ADDED', 'MODIFIED'] and pod.status.pod_ip is not None:
                self.ipset_peers.add(pod.status.pod_ip)

            elif event['type'] == 'DELETED':
                self.ipset_peers.delete(pod.status.pod_ip)


class Direction:

    def __init__(self, profile: 'Profile', spec: dict, dir: str = 'ingress'):
        self.profile = profile
        self.direction = dir
        self.spec = spec
        
        rules = profile.spec.get(self.direction, [])
        self.rules = [Rule(self, i, r) for i, r in enumerate(rules)]

        is_ingress = self.direction == 'ingress'

        if self.profile.type == 'TC':
            self.controller = TrafficController(is_ingress, self.filters)
        elif self.profile.type == 'VTT':
            self.controller = VttController(is_ingress, self.filters)
        else:
            raise RuntimeError('Unsupported controller type: ' + self.profile.type)

    def initialize(self, interface: str):
        self.interface = interface
 
        for rule in self.rules:
            rule.initialize()

        self.controller.initialize(self.interface, self.spec['impairment'])

        logging.info('Initialized %s direction of profile %s', self.direction, self.profile)

    def deinitialize(self):
        self.controller.deinitialize(self.interface, self.spec)

        for rule in self.rules:
            rule.deinitialize()

        logging.info('Deinitialized %s direction of profile %s', self.direction, self.profile)

    @property
    def filters(self):
        return [r.filter for r in self.rules]


class Profile:

    def __init__(self, obj: dict):
        self.name = obj['metadata']['name']
        self.uid = obj['metadata']['uid']
        self.spec = obj['spec']
        self.type = self.spec.get('impairmentType', 'TC')

        if 'ingress' in self.spec:
            self.ingress = Direction(self, self.spec['ingress'], 'ingress')

        if 'egress' in self.spec:
            self.egress = Direction(self, self.spec['egress'], 'egress')

    def initialize(self, interface: str):
        self.interface = interface

        if self.ingress:
            self.ingress.initialize(self.interface)

        if self.egress:
            self.egress.initialize(self.interface)

        logging.info('Initialized profile %s', self.name)
    
    def deinitialize(self):
        if self.ingress:
            self.ingress.deinitialize()

        if self.egress:
            self.egress.deinitialize()

        logging.info('Deinitialized profile %s', self.name)

    def match(self, pod):
        selector = LabelSelector(self.spec['podSelector'])

        return selector.match(pod.metadata.labels)

    def update(self, newp):
        # TODO: implement
        
        logging.info('Updating profile %s', self.name)

    @classmethod
    def list(cls):
        api = client.CustomObjectsApi()

        ret = api.list_cluster_custom_object(
                group='k8s-netem.riasc.eu',
                version='v1',
                plural='trafficprofiles')

        return map(cls, ret['items'])

    @classmethod
    def watch(cls, pod, interface):
        api = client.CustomObjectsApi()
        w = watch.Watch()

        profiles: Dict[str, Profile] = {}

        for event in w.stream(api.list_cluster_custom_object,
            group='k8s-netem.riasc.eu',
            version='v1',
            plural='trafficprofiles'):

            obj = event['object']
            uid = obj.metadata.uid

            new_profile = Profile(obj)
            old_profile = profiles.get(uid)

            if event['type'] in ['ADDED', 'MODIFIED']:
                if old_profile:
                    old_profile.update(new_profile)
                elif new_profile.match(pod):
                    profiles[uid] = new_profile

                    new_profile.initialize(interface)

            elif event['type'] == 'DELETED':
                new_profile.deinitialize()

                del profiles[uid]

    def __str__(self):
        return f'{self.name} ({self.type})<{self.uid}>