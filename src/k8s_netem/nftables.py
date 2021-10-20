import nftables
import logging
import json
import threading

_nftables = None
_nftables_lock = threading.Lock()

LOGGER = logging.getLogger('nft')


class NftablesError(RuntimeError):

    def __init__(self, rc: int, err: str):
        self.rc = rc
        self.err = err

        super().__init__(f'Failed to configure nftables: {err} ({rc})')


def nft(cmds):
    global _nftables

    if _nftables is None:
        LOGGER.info('Loading nftables')
        _nftables = nftables.Nftables()
        _nftables.validator = nftables.SchemaValidator()

    if len(cmds) == 0:
        return None

    for cmd in cmds:
        log_cmd(LOGGER, cmd)

    payload = {
        'nftables': cmds
    }

    _nftables_lock.acquire()

    rc, output, err = _nftables.json_cmd(payload)

    _nftables_lock.release()

    if output != '':
        LOGGER.trace('NFT Output: %s', json.dumps(output, indent=2))

    if rc != 0:
        raise NftablesError(rc, err)

    return output


def log_cmd(logger, cmd):
    for action, object in cmd.items():
        for type, object in object.items():
            logger.trace('NFT command: %s %s %s', action, type, json.dumps(object, indent=2))
