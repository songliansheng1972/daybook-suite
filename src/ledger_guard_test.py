#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daybook · append-only 判据回归（ledger guard）
Daybook · append-only criterion regression (ledger guard)
================================================
专挡「把「未变」判据退回 size+mtime」这种静默回退：并发烟雾测试（daybook_test.py）
在判据退回后仍会全绿，本文件不会。

Cases
  A 首次索引非空卷                              ⇒ rc=5（无封存证据·不写回），认基线后 0
  B 未变复跑两次                                ⇒ rc=0 且判「未变」，不得全扫
  C 纯追加一行                                  ⇒ rc=0，且走「只追加」
  D 全卷中部等长替换＋os.utime 恢复 mtime        ⇒ rc=3（等长改写）
  E 同一手法但不恢复 mtime                      ⇒ rc=3
  F 旧格式索引（fmt<2）                         ⇒ rc=0，报过期并全量重建
  G 删索引后等长替换                            ⇒ rc=3（索引缺失仍验哈希·不得洗成 5）
  H 删游标后等长替换                            ⇒ rc=5（证据缺失·不写回）
  I 游标写成 {}                                 ⇒ rc=5（不可信·不自动修好）
  J 替换后自己重写游标的 hash/size/mtime         ⇒ rc=3（与封存指纹不符·游标被改写）
  K 删索引加删游标                              ⇒ rc=5（证据缺失·不重建）
  L 正常追加后删索引                            ⇒ rc=5 且无 traceback（旧实现 FileNotFoundError rc=1）
  M 三件派生件全删                              ⇒ rc=5（无外部锚·复跑仍 5），认基线后 0
  N 索引缺失且卷变长、旧前缀被改                 ⇒ rc=3（不能因「卷变大」跳过前缀校验）
  O 违例态认基线                                ⇒ rc=3，三件派生件零变化（不替人认下篡改）

变异验证 / mutation check
  把 daybook.py 的同长判定临时改回 size+mtime，用 DAYBOOK_SRC 指向该副本运行本文件：
  D、E 必须红；恢复原码后必须全绿。用法：
    DAYBOOK_SRC=/tmp/mutant/daybook.py python3 ledger_guard_test.py

跑法 / Run: python3 ledger_guard_test.py
退出码 / Exit code: 0=全绿 1=有红
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# 被测 daybook.py：默认同目录；变异验证时用 DAYBOOK_SRC 指向临时副本
# The daybook.py under test: same directory by default; DAYBOOK_SRC points at a mutant copy.
SRC_BIN = os.environ.get('DAYBOOK_SRC') or os.path.join(HERE, 'daybook.py')

CONF = """[volumes]
账=账卷.txt

[entries]
head_regex=^(?:\\[#\\d+\\][ ]*)?\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}(?::\\d{2})?)\\]
tag_regex=^(?:\\[#\\d+\\][ ]*)?\\[\\d{4}[^\\]]*\\][ ]*\\[([^\\]]+)\\][ ]*\\[([^\\]]*)\\](?:[ ]*\\[([^\\]]*)\\])?
fields=volume,line,time,category,title,author

[rules]
category=tag:1
title=tag:2
author=tag:3

[index]
root=
out_dir=索引
index_prefix=index_
manifest=volumes.md

[trigger]
incremental=是
"""

FAILS = []
CHECKS = [0]


def _ok(name, cond, detail=''):
    CHECKS[0] += 1
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    if not cond:
        FAILS.append(name)
    return bool(cond)


def _make_volume(path, n=120, body=480):
    """造一条足以让「中部」落在头/尾 4K 窗口之外的正账。
    Build a volume long enough for its midpoint to sit outside the head/tail 4K windows."""
    with io.open(path, 'w', encoding='utf-8') as f:
        for i in range(n):
            f.write('[2026-11-13 10:%02d:%02d] [测试] [第%03d条] [皮特] %s\n'
                    % (i // 60, i % 60, i, '正文' * (body // 2)))


def _prepare(tmp):
    """把被测 daybook.py、safeio.py、daybook_append.py 拷进隔离目录，写 conf 与账卷。
    Copy the daybook.py under test plus safeio.py / daybook_append.py into an isolated directory
    with conf and volume.
    （index 的作者口径机检走 daybook_append.check_author_consistency，故须随拷。）
    (The index author-convention gate calls daybook_append.check_author_consistency, so it must be staged too.)"""
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(tmp, name))
    with io.open(os.path.join(tmp, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    _make_volume(os.path.join(tmp, '账卷.txt'))


def _run(tmp):
    # -B：被测脚本被拷进隔离目录运行（真实部署里它在包目录、不在账本里），
    # 关掉字节码缓存，免得 __pycache__ 冒充「账本被写」。
    # -B: the script is staged inside the isolated ledger here (in real deployment it lives in
    # the package dir), so suppress bytecode caching to keep __pycache__ out of the criterion.
    return subprocess.run([sys.executable, '-B', 'daybook.py', 'index'],
                          cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def _base(tmp):
    return subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'],
                          cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def _log(tag, r):
    print('    [%s] rc=%d' % (tag, r.returncode))
    out = (r.stdout + r.stderr).strip().splitlines()
    for line in out[:4]:
        print('      ' + line)


def _dir_hash(d):
    """目录内所有文件（按名排序）的联合 sha256：用于证明「一个字节都没写」。
    Combined sha256 of every file in a directory (name-sorted): proves nothing was written."""
    import hashlib as _h
    h = _h.sha256()
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            h.update(name.encode('utf-8'))
            h.update(io.open(p, 'rb').read())
    return h.hexdigest()


def _tamper_mid(path, start_frac):
    """中部等长替换一个数字字节（仍是数字 ⇒ 条目头仍合法，隔离出哈希判据）。
    Equal-length replacement of one digit near the middle (still a digit ⇒ the entry head stays
    valid, isolating the hash criterion from parsing/encoding drift)."""
    st = os.stat(path)
    b = bytearray(open(path, 'rb').read())
    pos = int(len(b) * start_frac)
    while pos < len(b) and not (48 <= b[pos] <= 57):
        pos += 1
    assert 4096 < pos < len(b) - 4096, 'tamper position must be outside head/tail 4K windows'
    b[pos] = ord('7') if b[pos] != ord('7') else ord('8')
    open(path, 'wb').write(bytes(b))
    return st, pos


def main():
    if not os.path.exists(SRC_BIN):
        print('找不到被测 daybook.py：%s' % SRC_BIN, file=sys.stderr)
        return 1
    work = tempfile.mkdtemp(prefix='daybook_guard_')
    try:
        _prepare(work)
        vol = os.path.join(work, '账卷.txt')
        idf = os.path.join(work, '索引', 'index_账.tsv')
        cp = os.path.join(work, '索引', '.cursor_账.json')
        sp = os.path.join(work, '索引', '.head_stamp.json')

        # A：首次索引非空卷 ⇒ 无任何封存证据，退 5 且不写回；认基线后才 0
        # A: first index of a non-empty volume has no sealed evidence ⇒ 5 and nothing written
        #    back; only an explicit baseline makes it 0
        root_before = set(os.listdir(work))
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('A 首次索引 ⇒ rc=5（无封存证据）', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('A 报「无任何封存证据」', '无任何封存证据' in txt)
        _ok('A 不写回游标/索引', not os.path.exists(cp) and not os.path.exists(idf))
        root_after = set(os.listdir(work))
        _ok('A 账本目录零变化（rc=5 不新增文件或目录·锁在临时目录）',
            root_before == root_after, '新增=%s' % sorted(root_after - root_before))
        _ok('A 账本根无 .safeio_lock 残留',
            not any(n.startswith('.safeio_lock') for n in root_after))
        _log('A', r)
        r = _run(work)
        _ok('A 未认基线前复跑仍 rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        r = _base(work)
        _ok('A 认基线 ⇒ rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        r = _run(work)
        _ok('A 认基线后 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)

        # D：中部等长替换 + 恢复 mtime ⇒ 必须违例（不是未变跳过）
        orig_d = io.open(vol, 'rb').read()
        st, pos = _tamper_mid(vol, 0.50)
        os.utime(vol, (st.st_atime, st.st_mtime))
        same_mtime = os.stat(vol).st_mtime == st.st_mtime
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('D mtime 已恢复原值', same_mtime)
        _ok('D 等长中部加恢复 mtime ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('D 明确报违例', ('违例' in txt) and ('等长改写' in txt),
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _ok('D 不得报「未变·跳过」', '未变·跳过' not in txt)
        _log('D', r)

        # 复位：把账本原文写回，指纹重新对上（违例已不再自动写回）
        # Reset: put the original volume bytes back so the fingerprints match again
        # (a violation no longer writes anything back)
        io.open(vol, 'wb').write(orig_d)
        r = _run(work)
        _ok('D 恢复原文后 复跑 rc=0', r.returncode == 0,
            'rc=%d | %s' % (r.returncode, (r.stdout + r.stderr).strip()[:160]))

        # E：同一手法、不恢复 mtime ⇒ 同样违例
        orig_e = io.open(vol, 'rb').read()
        st, pos = _tamper_mid(vol, 0.35)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('E 等长中部不恢复 mtime ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('E 明确报违例', ('违例' in txt) and ('等长改写' in txt))
        _log('E', r)
        io.open(vol, 'wb').write(orig_e)
        _run(work)

        # C：纯追加 ⇒ rc=0 且必须走「只追加」，不得全量重扫
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 12:00:00] [测试] [纯追加] [皮特] 追加正文\n')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('C 纯追加 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        _ok('C 走只追加路径', '只追加' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '只追加' in l)[:160])
        _ok('C 未触发全量重扫', '全扫' not in txt)
        _log('C', r)

        # F：旧格式索引（游标 fmt<2、口径戳无 index_fmt）⇒ 首跑报格式过期、全量重建、rc=0
        # F: legacy index format ⇒ report staleness, rebuild fully, rc=0
        cur = json.load(io.open(cp, encoding='utf-8'))
        cur.pop('fmt', None)
        cur.pop('content_hash', None)
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(cur, ensure_ascii=False))
        stamp = json.load(io.open(sp, encoding='utf-8'))
        stamp.pop('index_fmt', None)
        with io.open(sp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(stamp, ensure_ascii=False))
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('F 旧格式索引 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        _ok('F 报格式过期', ('格式过期' in txt) or ('旧游标格式' in txt),
            ' | '.join(l.strip() for l in txt.splitlines() if '过期' in l)[:160])
        _ok('F 全量重建', '全扫' in txt)
        cur2 = json.load(io.open(cp, encoding='utf-8'))
        _ok('F 游标已升 fmt=2', cur2.get('fmt') == 2 and bool(cur2.get('content_hash')),
            'fmt=%r' % cur2.get('fmt'))
        _log('F', r)

        # B：未变复跑两次 ⇒ rc=0 稳定，且正常跑也不得在账本根新增文件
        # B: two unchanged reruns ⇒ stable 0, and a normal run must not add files to the ledger root
        for i in (1, 2):
            before_b = set(os.listdir(work))
            r = _run(work)
            txt = r.stdout + r.stderr
            after_b = set(os.listdir(work))
            _ok('B 未变复跑#%d rc=0' % i, r.returncode == 0, 'rc=%d' % r.returncode)
            _ok('B 未变复跑#%d 判未变' % i, '未变·跳过' in txt and '全扫' not in txt)
            _ok('B 未变复跑#%d 账本根不新增文件' % i, before_b == after_b,
                '新增=%s' % sorted(after_b - before_b))

        # ── G–K：派生件被删/被改写，不得与「未变」同码 ──
        # ── G–K: deleted or rewritten derived artifacts must never share the unchanged status ──

        # G 删索引后等长替换 ⇒ 索引缺失仍验哈希 ⇒ 违例（rc=3），不得洗成证据缺失
        os.remove(idf)
        orig_g = io.open(vol, 'rb').read()
        _tamper_mid(vol, 0.45)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('G 删索引+等长替换 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('G 报「索引缺失但哈希不符」', '索引缺失但全卷哈希' in txt or '等长改写' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _ok('G 不得判未变', '未变·跳过' not in txt)
        _ok('G 不自动重建（违例后须恢复原文）', not os.path.exists(idf),
            'exists=%s' % os.path.exists(idf))
        _log('G', r)
        # 违例不写回：baseline 也拒（见 O）；恢复原文后再认基线
        # A violation writes nothing back and baseline refuses (see O); restore then baseline
        r = _base(work)
        _ok('G 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        io.open(vol, 'wb').write(orig_g)
        _base(work)

        # H 删游标后等长替换 ⇒ 证据缺失（rc=5）
        os.remove(cp)
        _tamper_mid(vol, 0.55)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('H 删游标+等长替换 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('H 报证据缺失（游标丢失）', '证据缺失' in txt and '游标' in txt)
        _ok('H 不得判未变', '未变·跳过' not in txt)
        _ok('H 不写回游标', not os.path.exists(cp))
        _log('H', r)
        r = _run(work)
        _ok('H 未认基线前复跑仍 5', r.returncode == 5, 'rc=%d' % r.returncode)
        _base(work)

        # I 游标写成 {} ⇒ 不可信，证据缺失（rc=5），且不自动修好
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write('{}')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('I 游标={} ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('I 报证据缺失且不得判未变', '证据缺失' in txt and '未变·跳过' not in txt)
        _ok('I 不自动重写游标', io.open(cp, encoding='utf-8').read().strip() == '{}')
        _log('I', r)
        _base(work)

        # J 替换后自己重写游标的 hash/size/mtime ⇒ 与封存指纹不符 ⇒ rc=3
        orig_j = io.open(vol, 'rb').read()
        orig_cp = io.open(cp, 'rb').read()
        st, _pos = _tamper_mid(vol, 0.40)
        import hashlib as _hashlib
        new_hash = _hashlib.sha256(open(vol, 'rb').read()).hexdigest()
        cur = json.load(io.open(cp, encoding='utf-8'))
        cur['content_hash'] = new_hash
        cur['size'] = os.path.getsize(vol)
        cur['mtime'] = os.path.getmtime(vol)
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(cur, ensure_ascii=False))
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('J 重写游标指纹 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('J 报派生件互相矛盾', '封存指纹' in txt or '被改写' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _log('J', r)
        io.open(vol, 'wb').write(orig_j)
        io.open(cp, 'wb').write(orig_cp)
        _run(work)

        # K 删索引加删游标 ⇒ 证据缺失（rc=5），不写回；认基线后才恢复
        os.remove(idf)
        os.remove(cp)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('K 删索引+删游标 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('K 报证据缺失', '证据缺失' in txt)
        _ok('K 不得判未变', '未变·跳过' not in txt)
        _ok('K 不自动重建索引入口', not os.path.exists(idf))
        _log('K', r)
        _base(work)

        # L 正常追加后删索引 ⇒ 卷变大分支不得数不存在的索引文件（旧实现 FileNotFoundError rc=1）
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 13:00:00] [测试] [再追加] [皮特] 追加正文\n')
        os.remove(idf)                   # 追加后立刻删索引，不给中间落盘机会
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('L 追加后删索引 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('L 无 Traceback（不崩）', 'Traceback' not in txt and 'FileNotFoundError' not in txt)
        _ok('L 报证据缺失', '证据缺失' in txt)
        _log('L', r)
        _base(work)

        # M 三件派生件全删 ⇒ 无外部锚 ⇒ rc=5，复跑仍 5；认基线才 0
        for q in (idf, cp, sp):
            if os.path.exists(q):
                os.remove(q)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('M 三件全删 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('M 报「无任何封存证据」', '无任何封存证据' in txt)
        _log('M', r)
        r = _run(work)
        _ok('M 未认基线前复跑仍 5', r.returncode == 5, 'rc=%d' % r.returncode)
        r = _base(work)
        _ok('M 认基线 ⇒ rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        r = _run(work)
        _ok('M 认基线后 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)

        # N 索引缺失且卷变长：旧前缀被改 ⇒ 仍须判 3（不能因「卷变大」跳过校验）
        os.remove(idf)
        orig_n = io.open(vol, 'rb').read()
        _tamper_mid(vol, 0.30)
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 14:00:00] [测试] [变长] [皮特] 变长追加\n')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('N 索引缺失+变长+旧前缀改 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('N 报旧前缀哈希不符', ('旧前缀' in txt) or ('前缀哈希不符' in txt))
        _log('N', r)
        r = _base(work)
        _ok('N 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        io.open(vol, 'wb').write(orig_n)
        _base(work)

        n_rows = sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1
        _ok('索引行数与卷条目一致', n_rows == 122, 'rows=%d' % n_rows)

        # O 违例态认基线 ⇒ rc=3 且三件派生件零变化（不替人认下篡改）
        os.remove(idf)
        before = _dir_hash(os.path.join(work, '索引'))
        _tamper_mid(vol, 0.60)
        r = _base(work)
        after = _dir_hash(os.path.join(work, '索引'))
        _ok('O 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('O 报「未写任何派生件」', '未写任何派生件' in (r.stdout + r.stderr))
        _ok('O 派生件零变化', before == after)
        _log('O', r)
        io.open(vol, 'wb').write(orig_n)
        _base(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('\n=== 判据回归 === %d 红 / %d 项' % (len(FAILS), CHECKS[0]))
    if FAILS:
        print('FAIL: ' + '；'.join(FAILS))
        return 1
    print('PASS: A–O 十五组用例全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main())
