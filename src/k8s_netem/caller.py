import logging
import subprocess
import shlex


class Caller:
    @classmethod
    def _call(cls, command: str):
        """Run command."""
        logging.info('Run: %s', command)
        subprocess.call(shlex.split(command))

    @classmethod
    def _check_call(cls, command: str):
        """Run command, raising CalledProcessError if it fails."""
        logging.info('Run: %s', command)
        subprocess.check_call(shlex.split(command))
