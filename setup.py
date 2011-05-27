__author__="Gabriel Burca"
__date__ ="2011-05-25"

import os
from setuptools import setup, find_packages

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup (
    name = 'BaGoMa',
    version = '1.10',
    author = 'Gabriel Burca',
    author_email = 'gburca-bagoma@ebixio.com',

    requires = ['imaplib', 'cPickle', 'pprint', 'hashlib', 'time', 'getpass',
      'optparse', 'email.parser'],

    scripts = ['bagoma.py'],

    url = 'http://sourceforge.net/projects/bagoma',
    download_url = 'http://sourceforge.net/projects/bagoma/files/',
    license = 'GPL: <http://gnu.org/licenses/gpl.html>',
    description = 'Script to backup GMail accounts',
#    long_description= """
#BaGoMa (BAckup GOogle MAil) backs-up and restores the contents of a GMail
#account. It can restore all the labels (folder structure), as well as the flags
#(seen/read, flagged) of a message.
#""",

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

