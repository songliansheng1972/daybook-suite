#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""缺陷的变异回归：把每条改回旧行为，测试必须红；恢复后必须绿。
Mutation regression: revert each fix to the old behavior — the test must go red; restore it — the test must go green.

批次一（1-4）：pull 位置判已回 / 身份不验签 / 根写死代码目录 / read_vol 无锁。
批次二（6-12）：digest 静默 0 条 / alarm 字串硬警 / limit 旧语义 / 锁不 flock /
               verify 自比自过 / sock_path 不净化 / digest 逐条重读 + dead_agents 逐 agent 重扫。
Batch 1 (1-4): position-based reply / no signature verification / hard-coded root / unlocked read.
Batch 2 (6-12): silent-zero digest / substring hard alarm / legacy limit / no flock /
               self-comparing verify / unsanitized sock_path / per-row reread + per-agent rescan.

做法：把本包复制到临时目录 → 用文本替换注入旧行为 → 在临时目录里跑对应单测。
Approach: copy this package to a temp dir → text-replace the old behavior in → run that single test there.
原始输出与 rc 全部打印。
Raw output and rc are printed for both runs.

用法：python3 orch_mutation_check.py
退出码：0=全部满足「变异红·原版绿」；1=有不服。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = 'orch_fixes_test.py'

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.locks', '.daybook_keys',
                                '.safeio_lock.*', '*.tmp')

# (编号, 名称, [(文件, 旧片段, 新片段), ...])
MUTATIONS = [
    (1, 'pull 改回按位置判已回', [(
        'orchestrator.py',
        """            if not e.get('id'):
                e['reply_state'] = 'unknown'
            elif e['id'] in replied:
                e['reply_state'] = 'replied'
                continue
            else:
                e['reply_state'] = 'pending'""",
        """            _pos_replied = any(entries[j]['author'] in (who, who_id)
                               for j in range(i + 1, len(entries)))
            if _pos_replied:
                e['reply_state'] = 'replied'
                continue
            if not e.get('id'):
                e['reply_state'] = 'unknown'
            else:
                e['reply_state'] = 'pending'""",
    )]),
    (2, '身份改回不验签', [(
        'orchestrator.py',
        """        if not e.get('sig'):
            return 'unsigned'""",
        """        if not e.get('sig'):
            return 'ok'""",
    )]),
    (3, '根解析改回写死代码目录', [
        ('orchestrator.py',
         "        self.ledger = self.vols['ledger']",
         "        self.ledger = os.path.join(HERE, '编排卷.txt')"),
        ('agent_message.py',
         """    return INBOX_VOL if root is None else _vp.resolve_volumes(root)['inbox']""",
         """    return INBOX_VOL"""),
    ]),
    (4, 'read_vol 改回无锁读', [(
        'safeio.py',
        """    with locked(path, shared=True):
        with open(path, 'rb') as f:
            raw = f.read()""",
        """    with open(path, 'rb') as f:
        raw = f.read()""",
    )]),
    (6, 'digest 改回静默 0 条 / 互见失败改回空串', [
        ('orchestrator.py',
         """    vols = _load_volumes(root)
    if not vols:
        errors.append('卷表为空：%s 的 [volumes] 未登记任何内容卷' % os.path.join(root, 'daybook.conf'))
        return [], 'no-volumes', errors""",
         """    vols = _load_volumes(root)
    if not vols:
        return [], 'volume-fallback', errors"""),
        ('orchestrator.py',
         """    except Exception as exc:
        err = '%s: %s' % (type(exc).__name__, exc)
        sys.stderr.write('⚠ 互见引用失败（卷=%s 行=%s）：%s\\n' % (vol, lineno, err))
        return '', err""",
         """    except Exception:
        return '', ''"""),
    ]),
    (7, 'alarm 改回自产中文字串判硬警', [(
        'orchestrator.py',
        """        hard = any(it.hard for it in issues)""",
        """        hard = any(('失联' in it.msg or '孤儿' in it.msg) for it in issues)""",
    )]),
    (8, '--limit 改回旧语义（负数少一条）', [
        ('orchestrator.py',
         """        if limit < 0:
            raise ValueError('limit 必须 ≥ 0（0=全部，正数=最近 N 条）')
""",
         ""),
        ('orchestrator.py',
         """    if args.cmd == 'digest' and args.limit < 0:
        ap.error('--limit 必须 ≥ 0（0=全部，正数=最近 N 条）')
""",
         ""),
    ]),
    (9, '锁改回不 flock', [(
        'agent_lock.py',
        """            fcntl.flock(fd, flag)""",
        """            pass  # mutated: no flock""",
    )]),
    (10, 'verify 改回无基准自比自过', [(
        'cross_ref.py',
        """        if not sha_prefix:
            raise ValueError('verify 需要基准 SHA8（[卷#L行-SHA8] 的后 8 位）；拒绝无基准自比')
        if not re.match(r'^[0-9a-f]{8}$', sha_prefix):
            raise ValueError('基准 SHA8 格式非法（须 8 位小写 hex）：%r' % (sha_prefix,))
        path = self._vol_path(vol)
        text = _read_text(path)
        cur = self._entry_hash(text, lineno)
        if cur is None:
            return False
        return cur == sha_prefix""",
        """        path = self._vol_path(vol)
        text = _read_text(path)
        cur = self._entry_hash(text, lineno)
        if cur is None:
            return False
        if sha_prefix and cur != sha_prefix:
            return False
        return True""",
    )]),
    (11, 'sock_path 改回不净化', [(
        'agent_message.py',
        """    path = os.path.join(SOCK_DIR, 'daybook_agent_%s.sock' % _safe_agent_token(agent_name))
    # Linux/macOS 的 sockaddr_un.sun_path 通常 104/108 字节（含结尾 NUL）；超出即无法 bind/connect。
    # Linux/macOS sockaddr_un.sun_path is typically 104/108 bytes including the trailing NUL; longer cannot bind/connect.
    if len(os.fsencode(path)) >= 104:
        raise ValueError('socket 路径过长（%d 字节 ≥104）：%s' % (len(os.fsencode(path)), path))
    return path""",
        """    return os.path.join(SOCK_DIR, 'daybook_agent_%s.sock' % agent_name)""",
    )]),
    (12, 'digest 逐条重读卷 + dead_agents 逐 agent 重扫', [
        ('orchestrator.py',
         """        return cr.make_ref(vol, int(lineno), index=index), ''""",
         """        return cr.make_ref(vol, int(lineno)), ''"""),
        ('agent_heartbeat.py',
         """    def dead_agents(self):
        \"\"\"扫所有出现过的 agent_id·返回 dead 列表（单遍扫描 + 时间戳阈值，不按字串判断）。
        Scan all agent_ids ever seen · return the dead list (one scan + timestamp threshold, never substring matching).\"\"\"
        now = _now_ts()
        limit = self.period * self.dead_after
        return [a for a, ts in self._last_beats().items() if (now - ts) >= limit]""",
         """    def dead_agents(self):
        agents = set()
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            if '[心跳]' not in line or 'alive' not in line:
                continue
            parts = [p.strip(' []') for p in line.split(']') if p.strip()]
            if len(parts) < 3:
                continue
            agent_id = parts[2]
            if agent_id and agent_id not in ('心跳', 'alive'):
                agents.add(agent_id)
        return [a for a in agents if not self.is_alive(a)]"""),
    ]),
]


def run_test(pkg, only):
    """在 pkg 目录里跑单测，返回 (rc, output)。 · Run the single test in pkg; return (rc, output)."""
    r = subprocess.run([sys.executable, TEST, '--only', str(only)],
                       cwd=pkg, capture_output=True, text=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def tail(output, n=12):
    lines = [x for x in output.strip().splitlines() if x.strip()]
    return '\n'.join('    ' + x for x in lines[-n:])


def make_mutant(n, subs):
    pkg = tempfile.mkdtemp(prefix='orch_mut%d_' % n)
    dest = os.path.join(pkg, 'pkg')
    shutil.copytree(HERE, dest, ignore=IGNORE)
    for fn, old, new in subs:
        path = os.path.join(dest, fn)
        with open(path, encoding='utf-8') as f:
            src = f.read()
        if old not in src:
            raise RuntimeError('变异锚点未命中：%s / %s' % (fn, old.splitlines()[0]))
        src = src.replace(old, new, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
    return pkg, dest


def main():
    ok = True
    print('=== 缺陷变异回归（批次一 4 + 批次二 7）===')
    for n, name, subs in MUTATIONS:
        pkg, mutant = make_mutant(n, subs)
        try:
            mrc, mout = run_test(mutant, n)
            print('\n-- 第 %d 条：%s --' % (n, name))
            print('  变异体 rc=%d（要求 ≠0）' % mrc)
            print(tail(mout))
            orc, oout = run_test(HERE, n)
            print('  原版   rc=%d（要求 =0）' % orc)
            print(tail(oout))
            good = (mrc != 0 and orc == 0)
            print('  判：%s' % ('红→绿 成立' if good else '不成立'))
            ok = ok and good
        finally:
            shutil.rmtree(pkg, ignore_errors=True)
    print('\n=== %s ===' % ('全部变异成立（红→绿）' if ok else '有不服'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
