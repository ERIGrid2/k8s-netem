'''Hold global configuration object

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

The only purpose is to have single global copy of the configuration
in memory for all modules that need it.

'''
import os
import json

CONF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'conf/'))

with open(CONF_PATH + "/server.json") as f:
    _CF = json.load(f)

def path(path):
    """Return absolute path for the relative path specified in the configuration file
    """
    return os.path.normpath(os.path.join(CONF_PATH, path))

