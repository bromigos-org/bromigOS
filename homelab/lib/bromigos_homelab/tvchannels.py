"""Locate the shared channel library in an installed package or a source checkout."""
import os
import sys

try:
    import bromigos_tvchannels as channels
except ModuleNotFoundError:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    local = os.path.join(root, 'lib')
    if os.path.isfile(os.path.join(local, 'bromigos_tvchannels.py')):
        sys.path.insert(0, local)
    else:
        sys.path.append('/usr/lib/bromigos/lib')
    import bromigos_tvchannels as channels
