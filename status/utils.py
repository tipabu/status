import errno
import hashlib
import json
import os
import pathlib
import tempfile
import time

import requests
try:
    import xattr
except ImportError:
    import os as xattr

CACHE_DIR = pathlib.Path(tempfile.gettempdir()) / 'status-cache'
DEFAULT_TTL = 3600


def cached_get(url, ttl=None):
    ttl = DEFAULT_TTL if ttl is None else ttl
    f = CACHE_DIR / hashlib.md5(url.encode('ascii')).hexdigest()[:8]
    now = time.time()
    if ttl:
        try:
            st = os.stat(f)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            cached = False
        else:
            cached = ((now - st.st_mtime) < ttl)

        if cached:
            with open(f, 'rb') as fp:
                return fp.read()
        # Else, make request & cache it
    data = requests.get(url).content
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(f, 'wb') as fp:
        fp.write(data)
        if hasattr(xattr, 'setxattr'):
            xattr.setxattr(f, b'user.url', url.encode('utf8'))
            xattr.setxattr(f, b'user.retrieved', str(now).encode('utf8'))
    return data


def cached_json(url, ttl=None):
    data = cached_get(url, ttl)
    try:
        return json.loads(data)
    except ValueError:
        # cache is bad?
        return json.loads(cached_get(url, 0))
