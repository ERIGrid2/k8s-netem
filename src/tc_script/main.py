import logging
import json
import sys
import shlex
import os
import subprocess
import inotify.adapters

DEBUG = 'DEBUG' in os.environ


def call(command: str):
    """Run command, raising CalledProcessError if it fails."""

    logging.info('Run: %s', command)
    subprocess.check_call(shlex.split(command))


def configure(config):
    flows = config.get('flows', [])
    dev = config.get('interface')
    if dev is None:
        raise RuntimeError('missing device')

    priomap = [str(0)] * 12
    try:
        call(f'tc qdisc del dev {dev} root')
    except subprocess.CalledProcessError:
        pass  # fails if now parent qdisc is present. so we ignore it

    call(f'tc qdisc add dev {dev} root handle 1: prio bands {len(flows)} priomap ' + ' '.join(priomap))

    i = 1
    for flow in flows:
        filter = flow.get('filter')
        if filter is None:
            raise RuntimeError('missing filter')

        fwmark = filter.get('fwmark')
        if type(fwmark) is not int:
            raise RuntimeError('missing fwmark')

        parameters = flow.get('parameters')
        delay = parameters['delay']

        call(f'tc filter add dev {dev} handle {fwmark} fw classid 1:{i}')
        call(f'tc qdisc add dev {dev} parent 1:{i} netem delay {delay} ')

        i += 1


def watch_for_changes(p):
    fullpath = os.path.abspath(p)
    path, filename = os.path.split(fullpath)

    i = inotify.adapters.Inotify()
    i.add_watch(path)

    logging.info('Watching for changes of: %s', fullpath)

    last_hash = None

    try:
        for event in i.event_gen(yield_nones=False):
            (_, type_names, path, filename) = event

            if filename != filename:
                continue

            if 'IN_MODIFY' not in type_names:
                continue

            with open(fullpath, 'r') as f:
                contents = f.read()
                new_hash = hash(contents)

            if new_hash != last_hash:
                yield event
                last_hash = new_hash

    finally:
        i.remove_watch(path)


def main():
    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    if len(sys.argv) != 2:
        logging.error('usage: %s config_file', sys.argv[0])
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
