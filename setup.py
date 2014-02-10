
import os
from setuptools import setup, find_packages
from version import __version__, __date__, __author__, __email__

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup (
    name = 'BaGoMa',
    version = __version__,
    author = __author__,
    author_email = __email__,

    # Declare dependencies
    install_requires = ['hashlib', 'argparse', 'email', 'lockfile'],

    scripts = ['bagoma.py', 'version.py', 'imap_utf7.py', 'gui.pyw'],

    url = 'http://sourceforge.net/projects/bagoma',
    download_url = 'http://sourceforge.net/projects/bagoma/files/',
    license = 'GPL: <http://gnu.org/licenses/gpl.html>',
    description = 'Script to backup GMail accounts',

    long_description = read('README'),

    classifiers = [
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'Operating System :: OS Independent',
        'Topic :: Communications :: Email',
        'Topic :: System :: Archiving :: Backup',
        'Topic :: Utilities',
        'Environment :: Console',
        'Programming Language :: Python',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        ],
)

