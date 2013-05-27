from __future__ import absolute_import, division, print_function, unicode_literals

import json

from tornado import ioloop

def d(x):
    print(json.dumps(x, indent=4))

def add_future(future):
    ioloop.IOLoop.instance().add_future(future, check_future)

def check_future(future):
    # If there was an exception, this will reraise it
    future.result()
