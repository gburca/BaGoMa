__author__="Gabriel Burca"
__date__ ="2014-02-09"

import os
from setuptools import setup, find_packages

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup (
    name = 'BaGoMa',
    version = '1.40',
    author = 'Gabriel Burca',
    author_email = 'gburca-bagoma@ebixio.com',

    requires = ['imaplib', 'cPickle', 'pprint', 'time', 'getpass'],
    # Declare dependencies
    install_requires = ['hashlib', 'argparse', 'email', 'lockfile'],

    scripts = ['bagoma.py', 'imap_utf7.py', 'gui.pyw'],

    url = 'http://sourceforge.net/projects/bagoma',
    download_url = 'http://sourceforge.net/projects/bagoma/files/',
    license = 'GPL: <http://gnu.org/licenses/gpl.html>',
    description = 'Script to backup GMail accounts',

    long_description = read('../README'),

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

