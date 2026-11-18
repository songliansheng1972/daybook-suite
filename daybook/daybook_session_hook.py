#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""归档本工作区的 Copilot 会话事件与发生变更的源码文件。
Archive Copilot session events and changed source files for this workspace.

根的口径（明写·独立根）：本件的账本根**就是脚本所在目录**（ROOT），不读 conf 的
`[index] root`，也不接受 `--home`。原因：它随 VS Code 任务安装在工作区里，必须把
「工作区源码快照」和「会话原件」落到同一目录；conf 的账本根可能指向别处，跟着走会
把工作区源码归档到另一个账本。`--state` / `--events-root` 可以指向别处，但 `--state`
仍受 ROOT 的写能力约束（越界由 safeio 拒绝，rc=6）。
Root rule (explicit independent root): this entry's ledger root **is the script's own
directory** (ROOT). It does not read conf's `[index] root` and accepts no `--home`: the VS
Code task installs it inside the workspace, and the workspace code snapshot plus session
originals must land in that same directory; following conf's root could archive workspace
sources into a different ledger. `--state` / `--events-root` may point elsewhere, but
`--state` is still constrained by ROOT's write capability (safeio refuses out-of-root).
"""
import argparse

import errors
import datetime
import glob
import hashlib
import json
import os
import sys
import time

import daybook_record

# ★ 独立根（明写，见模块 docstring）：不随 conf 的 [index] root 走，也不接受 --home。
# ★ Independent root (documented above): it does not follow conf's [index] root and has no --home.
ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EVENTS = os.path.expanduser('~/.copilot/session-state')
DEFAULT_STATE = os.path.join(ROOT, '开发卷', '.会话归档游标.json')
LABEL = 'com.daybook.workspace-session-archive'
CODE_EXTENSIONS = {
    '.py', '.pyi', '.sh', '.bash', '.zsh', '.c', '.h', '.cc', '.cpp',
    '.hpp', '.bas', '.f', '.for', '.f90', '.js', '.jsx', '.ts', '.tsx',
    '.rs', '.go', '.java', '.kt', '.swift', '.rb', '.php', '.sql',
}
SKIP_DIRS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__', '备份',
    '开发卷', '对话原件',
}


def local_stamp(value):
    parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.astimezone().strftime('%Y%m%d_%H%M%S')


def atomic_json(path, value, root):
    """写账本内的 json（root 为入口打开的 Root 句柄；越界即拒绝）。
    Write a json inside the ledger (root is the Root handle opened by the entry; out-of-root is
    refused)."""
    from safeio import locked, WriteMode
    with locked(root) as lr:
        lr.write(lr.root.rel_of(path, 'daybook_session_hook.atomic_json'),
                 json.dumps(value, ensure_ascii=False, sort_keys=True),
                 mode=WriteMode.REPLACE)


def scan_code():
    files = {}
    for current, dirs, names in os.walk(ROOT):
        dirs[:] = [
            name for name in dirs
            if name not in SKIP_DIRS and not name.startswith('.')
        ]
        for name in names:
            if os.path.splitext(name)[1].lower() not in CODE_EXTENSIONS:
                continue
            path = os.path.join(current, name)
            with open(path, 'rb') as source:
                content = source.read()
            files[os.path.relpath(path, ROOT)] = content
    return files


def archive_message(role, event, workspace, root):
    content = event['data'].get('content')
    if not isinstance(content, str) or not content:
        return False
    source_id = event['data'].get('messageId') or event.get('id', '')
    title = '%s-%s' % (role, source_id[:12] or 'message')
    path, digest, _ = daybook_record.record(
        role, title, content.encode('utf-8'), local_stamp(event['timestamp']), root=root)
    print('已归档%s消息：%s SHA256=%s' % (role, path, digest), flush=True)
    return True


def archive_code_changes(files, previous, stamp, root):
    current_hashes = {}
    for relative_path, content in files.items():
        digest = hashlib.sha256(content).hexdigest()
        current_hashes[relative_path] = digest
        if previous.get(relative_path) == digest:
            continue
        path, saved_digest, _ = daybook_record.record(
            '实验代码', relative_path, content, stamp, root=root)
        print('已归档代码变更：%s SHA256=%s' % (path, saved_digest), flush=True)
    for relative_path, digest in previous.items():
        if relative_path not in current_hashes:
            tombstone = ('删除文件：%s\n原 SHA256：%s\n' % (
                relative_path, digest)).encode('utf-8')
            path, saved_digest, _ = daybook_record.record(
                '实验代码', relative_path + '-deleted', tombstone, stamp, root=root)
            print('已归档代码删除记录：%s SHA256=%s' % (
                path, saved_digest), flush=True)
    return current_hashes


def event_files(events_root):
    return sorted(glob.glob(os.path.join(events_root, '*', 'events.jsonl')))


def load_state(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as state_file:
        return json.load(state_file)


def initialize_state(events_root, state_path, root):
    state = {
        'offsets': {},
        'workspaces': {},
        'code_hashes': {
            name: hashlib.sha256(content).hexdigest()
            for name, content in scan_code().items()
        },
    }
    for path in event_files(events_root):
        state['offsets'][path] = os.path.getsize(path)
        with open(path, 'rb') as events_file:
            first_line = events_file.readline()
        if first_line:
            first_event = json.loads(first_line.decode('utf-8'))
            if first_event.get('type') == 'session.start':
                context = first_event.get('data', {}).get('context') or {}
                cwd = context.get('cwd')
                if cwd:
                    session_id = os.path.basename(os.path.dirname(path))
                    state['workspaces'][session_id] = os.path.realpath(cwd)
    from safeio import locked
    with locked(root) as lr:
        lr.mkdirs_path(os.path.dirname(state_path), 'daybook_session_hook.state_dir')
    atomic_json(state_path, state, root)
    return state


def handle_event(event, session_id, state, workspace, root):
    kind = event.get('type')
    data = event.get('data') or {}
    if kind == 'session.start':
        context = data.get('context') or {}
        cwd = context.get('cwd')
        if cwd:
            state['workspaces'][session_id] = os.path.realpath(cwd)
        return

    if state['workspaces'].get(session_id) != workspace:
        return

    if kind == 'user.message':
        if not archive_message('用户', event, workspace, root):
            print('跳过无文本的用户消息事件：%s' % event.get('id'), file=sys.stderr)
    elif (kind == 'assistant.message'
          and data.get('phase') == 'final_answer'):
        if not archive_message('助手', event, workspace, root):
            print('跳过空的助手最终回复事件：%s' % event.get('id'), file=sys.stderr)
    elif kind == 'assistant.turn_end':
        files = scan_code()
        state['code_hashes'] = archive_code_changes(
            files, state['code_hashes'], local_stamp(event['timestamp']), root)


def process_once(events_root, state_path, workspace, root, initialize=False):
    from safeio import locked
    with locked(root) as lr:
        lr.mkdirs_path(os.path.dirname(state_path), 'daybook_session_hook.state_dir')
    state = load_state(state_path)
    fresh = False
    if state is None:
        if not initialize:
            state = initialize_state(events_root, state_path, root)
            print('已建立初始游标；既有会话不回灌。', flush=True)
            return
        state = {'offsets': {}, 'workspaces': {}, 'code_hashes': {}}
        # --initialize：显式从零建游标。落盘放在本轮处理之后（见下）——本轮若以 3/5 失败，
        # 就不许留下状态文件（非零退出零落盘）；没有可消费事件时也要落盘，否则「已建立」不成立。
        # --initialize builds the cursor from zero; the write happens after this round (below) so a
        # 3/5 failure leaves no state file (zero writes on a non-zero exit). With nothing to
        # consume it still persists, otherwise "established" would be false.
        fresh = True

    changed = False
    for path in event_files(events_root):
        if path not in state['offsets']:
            state['offsets'][path] = 0
            changed = True
        offset = state['offsets'][path]
        with open(path, 'rb') as source:
            source.seek(offset)
            chunk = source.read()
        complete_length = chunk.rfind(b'\n') + 1
        if complete_length == 0:
            continue
        lines = chunk[:complete_length].splitlines()
        session_id = os.path.basename(os.path.dirname(path))
        for raw_line in lines:
            if not raw_line:
                continue
            event = json.loads(raw_line.decode('utf-8'))
            handle_event(event, session_id, state, workspace, root)
        state['offsets'][path] = offset + complete_length
        changed = True
    if changed or fresh:
        atomic_json(state_path, state, root)
    if fresh:
        print('已建立初始游标（--initialize：从零开始，既有事件不跳过）。', flush=True)


def install(root):
    vscode_dir = os.path.join(ROOT, '.vscode')
    tasks_path = os.path.join(vscode_dir, 'tasks.json')
    from safeio import locked
    with locked(root) as lr:
        lr.mkdirs_path(vscode_dir, 'daybook_session_hook.vscode_dir')
    if os.path.exists(tasks_path):
        with open(tasks_path, encoding='utf-8') as tasks_file:
            config = json.load(tasks_file)
    else:
        config = {'version': '2.0.0', 'tasks': []}
    tasks = [task for task in config.get('tasks', []) if task.get('label') != LABEL]
    tasks.append({
        'label': LABEL,
        'type': 'process',
        'command': sys.executable,
        'args': ['${workspaceFolder}/daybook_session_hook.py', 'watch'],
        'options': {'cwd': '${workspaceFolder}'},
        'isBackground': True,
        'problemMatcher': [],
        'runOptions': {'runOn': 'folderOpen'},
    })
    config['version'] = '2.0.0'
    config['tasks'] = tasks
    atomic_json(tasks_path, config, root)
    print('已配置 VS Code 文件夹打开后台任务：%s' % tasks_path)
    print('在 VS Code 首次允许自动任务后，归档器会随工作区打开而运行。')


def uninstall(root):
    tasks_path = os.path.join(ROOT, '.vscode', 'tasks.json')
    if not os.path.exists(tasks_path):
        print('VS Code 自动归档任务尚未配置。')
        return
    with open(tasks_path, encoding='utf-8') as tasks_file:
        config = json.load(tasks_file)
    tasks = [task for task in config.get('tasks', []) if task.get('label') != LABEL]
    config['tasks'] = tasks
    atomic_json(tasks_path, config, root)
    print('已从 VS Code 任务配置移除自动归档任务。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    watcher = subparsers.add_parser('watch')
    watcher.add_argument('--events-root', default=DEFAULT_EVENTS)
    watcher.add_argument('--state', default=DEFAULT_STATE)
    watcher.add_argument('--workspace', default=ROOT)
    watcher.add_argument('--once', action='store_true')
    watcher.add_argument('--initialize', action='store_true')
    subparsers.add_parser('install')
    subparsers.add_parser('uninstall')
    args = parser.parse_args()

    # ★ 步骤 2：入口只打开一次账本根句柄，向下传 Root（不再传根路径字符串）。
    # ★ Step 2: the entry opens the ledger-root handle once and passes the Root down.
    from safeio import Root
    try:
        root = Root._from_dir_path(ROOT, 'daybook_session_hook.main')
    except RuntimeError as exc:
        # 入口期的根问题 = 2；运行期写拒绝走顶层收口 → 6。
        # An entry-time root problem is 2; runtime write refusals travel to the top boundary → 6.
        raise errors.ConfigError(str(exc))

    if args.command == 'install':
        install(root)
        return 0
    if args.command == 'uninstall':
        uninstall(root)
        return 0

    events_root = os.path.realpath(args.events_root)
    workspace = os.path.realpath(args.workspace)
    if not os.path.isdir(events_root):
        parser.error('Copilot session event directory not found: %s' % events_root)
    if args.once:
        process_once(events_root, args.state, workspace, root, args.initialize)
        return 0
    process_once(events_root, args.state, workspace, root, args.initialize)
    print('监听工作区：%s' % workspace, flush=True)
    while True:
        time.sleep(1)
        process_once(events_root, args.state, workspace, root, True)


def _entry():
    """入口期分类：读不到/读坏输入 → 证据缺失（5）；根/参数解析失败 → 配置错（2）。
    Entry-time classification: unreadable/corrupt input → missing evidence (5); root/argument
    resolution failure → config error (2)."""
    try:
        return main()
    except errors.DaybookError:
        raise
    except json.JSONDecodeError as exc:
        raise errors.EvidenceMissing('会话归档器失败：%s' % exc)
    except OSError as exc:
        raise errors.EvidenceMissing('会话归档器失败：%s' % exc)
    except ValueError as exc:
        raise errors.ConfigError(str(exc))


if __name__ == '__main__':
    sys.exit(errors.run_entry(_entry))
