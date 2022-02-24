'''Account information library

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
'''

from passlib.apps import custom_app_context as pwd_context
import flexe.lib.configuration as conf
import os

# WARNING: The solution applied reads the full "user/passwd" into
# memory, and overwrites all data on update => There should be only
# ONE process actually doing the update: this simple solution fails if
# multiple processes attempt to update the file at same time -- the
# last process to write, wins (and updates from others may be lost).

USERS = conf.path(conf._CF['users'])
ADMIN = "flexe"


def _load():
    users = {}
    if os.path.exists(USERS):
        with open(USERS, "r") as f:
            for line in f.read().splitlines():
                name, _, hash = line.partition(':')
                if not name or name[0] == '#':
                    continue  # ignore bad lines and "comments"
                users[name] = hash
    else:
        # No USERS file, create default admin user with empty password.
        users[ADMIN] = pwd_context.encrypt('')
    return users


def _save(users):
    # Write user/passwd dictionary into file
    with open(USERS, "w") as f:
        for name, hash in users.iteritems():
            f.write(name + ':' + hash + '\n')


def check_user(user, password):
    """Return True, if password matches for user, and False otherwise"""

    users = _load()
    if user in users:
        return pwd_context.verify(password, users[user])
    return False


def add_user(user, password):
    """Add new user and password

    Return True if success, otherwise False (user already existed)
    """
    users = _load()
    if user not in users:
        users[user] = pwd_context.encrypt(password)
        _save(users)
        return True
    return False


def password(user, oldpass, newpass):
    """Change password of an existing user"""

    users = _load()
    if user in users:
        if pwd_context.verify(oldpass, users[user]):
            users[user] = pwd_context.encrypt(newpass)
            _save(users)
            return True
    return False
