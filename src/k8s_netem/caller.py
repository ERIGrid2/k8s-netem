import logging
import subprocess
import shlex

LOGGER = logging.getLogger('call')


class Caller:
    @classmethod
    def _call(cls, command: str):
        """Run command."""
        LOGGER.info('Run: %s', command)
        subprocess.call(shlex.split(command))

    @classmethod
    def _check_call(cls, command: str):
        """Run command, raising CalledProcessError if it fails."""
        LOGGER.info('Run: %s', command)
        subprocess.check_call(shlex.split(command))


def call(command: str):
    """Run command."""
    LOGGER.info('Run: %s', command)
    subprocess.call(shlex.split(command))


def check_call(command: str):
    """Run command, raising CalledProcessError if it fails."""
    LOGGER.info('Run: %s', command)
    subprocess.check_call(shlex.split(command))
