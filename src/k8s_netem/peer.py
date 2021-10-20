from __future__ import annotations
from typing import TYPE_CHECKING, Dict
import logging
import threading

from kubernetes import watch, client
import ipaddress

from k8s_netem.match import LabelSelector
from k8s_netem.resource import Resource

if TYPE_CHECKING:
    from k8s_netem.direction import Rule


class Namespace:

    def __init__(self, peer, name=None):
        self.peer = peer
        self.name = name

        self.logger = logging.getLogger(f'namespace:{name}')

        self.thread = threading.Thread(target=self.watch_pods)
        self.watch = None

    def init(self):
        self.logger.info('Initialize namespace watcher %s', self.name)
        self.thread.start()

    def deinit(self):
        self.logger.info('Deinitialize namespace watcher %s', self.name)

        if self.thread.is_alive():
            if self.watch:
                self.watch.stop()
            self.thread.join(0.0)

    def watch_pods(self):
        self.logger.info('Started watching pods for %s', self.peer.spec)

        self.watch = watch.Watch()
        v1 = client.CoreV1Api()

        selector = LabelSelector(self.peer.spec['podSelector']).to_labelselector()
        stream_args = {
            'label_selector': selector
        }

        if self.name:
            stream_func = v1.list_namespaced_pod
            stream_args['namespace': self.name]
        else:
            stream_func = v1.list_pod_for_all_namespaces

        for event in self.watch.stream(stream_func, **stream_args):
            self.peer.handle_pod_event(event)


class Peer(Resource):

    def __init__(self, rule: Rule, index: int, spec):
        super().__init__(spec)

        self.logger = logging.getLogger(f'peer:{rule.direction.name}-{rule.index}-{index}')

        self.rule = rule
        self.index = index

        self.thread = threading.Thread(target=self.watch_namespaces)
        self.namespaces: Dict[str, Namespace] = {}
        self.watch = None

    def init(self):
        self.logger.info('Initialize peer: %s', self.spec)

        if 'namespaceSelector' in self.spec:
            self.thread.start()

        elif 'podSelector' in self.spec:
            ns = Namespace(self)
            ns.init()

            self.namespaces['all'] = ns

    def deinit(self):
        self.logger.info('Deinitialize peer: %s', self.spec)

        if self.thread.is_alive():
            if self.watch:
                self.watch.stop()
            self.thread.join(0.0)

        for _, ns in self.namespaces.items():
            ns.deinit()

    def watch_namespaces(self, peer):
        self.logger.info('Started watching namespaces for %s', peer)

        self.watch = watch.Watch()
        v1 = client.CoreV1Api()

        selector = LabelSelector(peer['namespaceSelector']).to_labelselector()
        stream_args = {
            'selector': selector
        }

        for event in self.watch.stream(v1.list_namespace, **stream_args):
            self.handle_namespace_event(event)

    def handle_namespace_event(self, event):
        type = event['type']
        ns = event['object']

        uid = ns.metadata.uid

        self.logger.info('%s %s %s', type.capitalize(),
                         ns.kind,
                         ns.metadata.name)

        if type == 'ADDED':
            ns = Namespace(self, ns.metadata.name)
            ns.init()

            self.namespaces[uid] = ns

        elif type == 'DELETED':
            ns = self.namespaces[uid]
            ns.deinit()

            del self.namespaces[uid]

    def handle_pod_event(self, event):
        pod = event['object']
        type = event['type']

        if pod.status.pod_ip is None:
            self.logger.debug('Pod is missing IP address. Skipping')
            return

        verb = {
            'MODIFIED': 'in',
            'ADDED': 'to',
            'DELETED': 'from'
        }

        if type in ['MODIFIED', 'ADDED', 'DELETED']:
            self.logger.info('%s %s %s set %s for pod %s/%s',
                             type.capitalize(),
                             pod.status.pod_ip,
                             verb[type],
                             self.rule.set_nets_name,
                             pod.metadata.namespace,
                             pod.metadata.name)

            cidr = ipaddress.IPv4Network(pod.status.pod_ip)

            if type == 'DELETED':
                self.rule.delete_net(cidr)
            else:
                self.rule.add_net(cidr, f'{pod.metadata.namespace}/{pod.metadata.name}')
