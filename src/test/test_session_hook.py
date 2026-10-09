#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daybook_session_hook


class SessionHookTests(unittest.TestCase):
    def write_event(self, stream, event):
        stream.write((json.dumps(event) + '\n').encode('utf-8'))
        stream.flush()

    def test_archives_new_user_and_final_answer_only_for_workspace(self):
        workspace = os.path.realpath('/tmp/daybook-hook-test')
        with tempfile.TemporaryDirectory() as temporary:
            session_dir = os.path.join(temporary, 'session-a')
            os.makedirs(session_dir)
            event_path = os.path.join(session_dir, 'events.jsonl')
            state_path = os.path.join(temporary, 'state.json')
            with open(event_path, 'wb') as stream:
                self.write_event(stream, {
                    'id': 'start-a',
                    'type': 'session.start',
                    'timestamp': '2026-10-06T00:00:00Z',
                    'data': {'context': {'cwd': workspace}},
                })
            other_dir = os.path.join(temporary, 'session-b')
            os.makedirs(other_dir)
            other_path = os.path.join(other_dir, 'events.jsonl')
            with open(other_path, 'wb') as stream:
                self.write_event(stream, {
                    'id': 'start-b',
                    'type': 'session.start',
                    'timestamp': '2026-10-06T00:00:00Z',
                    'data': {'context': {'cwd': '/tmp/another-workspace'}},
                })

            daybook_session_hook.process_once(temporary, state_path, workspace)
            archived = []
            with mock.patch.object(
                    daybook_session_hook, 'archive_message',
                    side_effect=lambda role, event, root: (
                        archived.append((role, event['data']['content'])) or True
                    )):
                with open(event_path, 'ab') as stream:
                    self.write_event(stream, {
                        'id': 'user-1',
                        'type': 'user.message',
                        'timestamp': '2026-10-06T00:01:00Z',
                        'data': {'content': '原始问题'},
                    })
                    self.write_event(stream, {
                        'id': 'commentary-1',
                        'type': 'assistant.message',
                        'timestamp': '2026-10-06T00:01:01Z',
                        'data': {'phase': 'commentary', 'content': '进度消息'},
                    })
                    self.write_event(stream, {
                        'id': 'answer-1',
                        'type': 'assistant.message',
                        'timestamp': '2026-10-06T00:01:02Z',
                        'data': {'phase': 'final_answer', 'content': '最终回复'},
                    })
                with open(other_path, 'ab') as stream:
                    self.write_event(stream, {
                        'id': 'user-other',
                        'type': 'user.message',
                        'timestamp': '2026-10-06T00:01:03Z',
                        'data': {'content': '其它工作区问题'},
                    })
                daybook_session_hook.process_once(
                    temporary, state_path, workspace)

            self.assertEqual(archived, [
                ('用户', '原始问题'),
                ('助手', '最终回复'),
            ])

    def test_archives_changed_code_bytes(self):
        with mock.patch.object(
                daybook_session_hook.daybook_record, 'record',
                return_value=('archive.txt', 'digest', '')) as record_mock:
            hashes = daybook_session_hook.archive_code_changes(
                {'src/experiment.py': b'print("new")\n'},
                {'src/experiment.py': 'old-digest'},
                '20261006_000000')
        self.assertEqual(
            hashes['src/experiment.py'],
            hashlib.sha256(b'print("new")\n').hexdigest())
        record_mock.assert_called_once_with(
            '实验代码',
            'src/experiment.py',
            b'print("new")\n',
            '20261006_000000')


if __name__ == '__main__':
    unittest.main()
