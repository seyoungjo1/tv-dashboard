"""HTML bundle replacement must retain every dependency on repeat uploads."""
import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from tvrelay.ui import Api


class UploadTest(unittest.TestCase):
    def test_replacing_bundle_resends_unchanged_and_pending_assets(self):
        class Relay:
            tv = 'osan'
            def __init__(self):
                self.jobs = []
            def submit(self, job):
                self.jobs.append(job)
                return 'upload-%d' % len(self.jobs)

        with tempfile.TemporaryDirectory() as tmp:
            api, relay = Api(Path(tmp)), Relay()
            api.relay = lambda: relay
            api.state = lambda max_age=0: None
            files = {'dash/index.html': b'<script src="_index_files/js/react.js"></script>',
                     'dash/_index_files/js/react.js': b'window.React={};',
                     'dash/_index_files/css/theme.css': b'body{color:red}',
                     'dash/_index_files/css/res/font.woff2': b'font',
                     'dash/_index_files/img/photo.png': b'photo',
                     'dash/_index_files2/keep.js': b'keep'}
            for queued in (False, True):
                with self.subTest(queued=queued):
                    api.tree = {p: {'p': p, 'd': False, 's': len(d), 'h': hashlib.sha256(d).hexdigest()}
                                for p, d in files.items()}
                    api.queued = {p: {'h': hashlib.sha256(d).hexdigest(), 'id': 'old', 'at': time.time()}
                                  for p, d in files.items()} if queued else {}
                    ops = [{'op': 'delete', 'path': 'dash/_index_files', 'recursive': True}]
                    ops += [{'op': 'put', 'path': p, 'stage': api.put_stage(d)['id']} for p, d in files.items()]
                    result = api.send({'ops': ops})
                    job = relay.jobs[-1]
                    store = dict(files)
                    for op in job.ops:
                        if op['op'] == 'delete':
                            store = {p: d for p, d in store.items() if not p.startswith(op['path'] + '/')}
                        elif op['op'] == 'put':
                            store[op['path']] = b''.join(job.chunks[int(c[1:])] for c in op['chunks'])
                    self.assertEqual(store, files)
                    self.assertEqual(result['skipped'], ['dash/index.html', 'dash/_index_files2/keep.js'])
                    self.assertEqual([op['path'] for op in job.ops[1:]], list(files)[1:-1])
