import logging
import json
import sys
import os
import inotify.adapters

from k8s_netem.caller import call, check_call

import k8s_netem.log as log

LOGGER = logging.getLogger('tc-script')


def configure(config):
    LOGGER.info('Applying configuration: %s', json.dumps(config, indent=2))

    flows = config.get('flows', [])
    dev = config.get('interface')
    if dev is None:
        raise RuntimeError('missing device')

    priomap = [str(0)] * 16
    call(f'tc qdisc delete dev {dev} root')
    check_call(f'tc qdisc add dev {dev} root handle 1: prio bands {len(flows)+2} priomap ' + ' '.join(priomap))

    i = 2  # band 1 is for non-filtered flows
    for flow in flows:
        filter = flow.get('filter')
        if filter is None:
            raise RuntimeError('missing filter')

        fwmark = filter.get('fwmark')
        if type(fwmark) is not int:
            raise RuntimeError('missing fwmark')

        parameters = flow.get('parameters')
        delay = parameters['netem']['delay']

        check_call(f'tc filter add dev {dev} handle {fwmark} fw classid 1:{i}')
        check_call(f'tc qdisc add dev {dev} parent 1:{i} netem delay {delay} ')

        i += 1

    call(f'tc qdisc show dev {dev}')
    call(f'tc filter show dev {dev}')
    call(f'tc class show dev {dev}')


def watch_for_changes(p):
    fullpath = os.path.abspath(p)
    path, filename = os.path.split(fullpath)

    i = inotify.adapters.Inotify()
    i.add_watch(path)

    LOGGER.info('Watching for changes of: %s', fullpath)

    last_hash = None

    try:
        for event in i.event_gen(yield_nones=False):
            (_, type_names, path, filename) = event

            if filename != filename:
                continue

            if 'IN_MODIFY' not in type_names:
                continue

            st = os.stat(fullpath)
            if st.st_size == 0:
                continue

            LOGGER.info(st)

            with open(fullpath, 'r') as f:
                contents = f.read()
                new_hash = hash(contents)

            if new_hash != last_hash:
                yield event
                last_hash = new_hash

    finally:
        i.remove_watch(path)


def main():
    log.setup()

    if len(sys.argv) != 2:
        LOGGER.error('usage: %s config_file', sys.argv[0])
        sys.exit(-1)

    filename = os.path.abspath(sys.argv[1])

    # Initial configuration
    with open(filename, 'r') as f:
        last_config = json.load(f)
        configure(last_config)

    for event in watch_for_changes(filename):
        print(event)

        with open(filename, 'r') as f:
            last_config = json.load(f)
            configure(last_config)
