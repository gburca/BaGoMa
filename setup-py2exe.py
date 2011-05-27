from distutils.core import setup
import py2exe

setup(
    console=['bagoma.py'],
    # Bundle zipfile with executable
    zipfile = None,
    options = {"py2exe" : {"compressed" : True,
                           # 1 = bundle everything
                           # 2 = bundle everything except Python interpreter
                           # 3 = don't bundle (default)
                           "bundle_files" : 1,
                          },
              }

)
