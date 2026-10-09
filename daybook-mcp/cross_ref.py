#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""跨卷引用（W-DB-023-G3·第 3 项）
================================================
- 引用格式：[卷名#L行号-SHA256前8位]  如 [协作卷#L1392-a1b2c3d4]
- 解析引用·定位条目原文
- 校验 SHA-256·防篡改（条目被改 → hash 不匹配 → 报违例）
- 反向引用：扫所有卷找出引用本条目的地方
- 零依赖：仅用 Python 3 标准库（hashlib/re/os）

用法：
  from cross_ref import CrossRef
  cr = CrossRef(root='.')
  ref = cr.make_ref('协作卷', 1392)            # 生成引用字符串
  entry = cr.resolve('协作卷', 1392)          # 读条目原文
  ok  = cr.verify('协作卷', 1392)             # 校验 hash
  backs = cr.find_backrefs('协作卷', 1392)    # 反向引用
"""
import os, re, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))

# 引用正则：[卷名#L行号-SHA256前8位]
REF_RE = re.compile(r'\[([^\[#]+?)#L(\d+)-([0-9a-f]{8})\]')

# 条目头正则（与 daybook.conf 一致）
HEAD_RE = re.compile(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]')


def _read_text(path):
    """读卷·自动处理编码·走 safeio.read_vol（统一口径）。"""
    from safeio import read_vol
    text, _enc, _why = read_vol(path)
    return text


def _entry_at(text, lineno):
    """取指定起始行号的条目块·单遍扫描·返回 (块文本, 起始行, 末尾行)。
    lineno 从 1 开始。"""
    lines = text.split('\n')
    if lineno < 1 or lineno > len(lines):
        return None
    # 找该行的条目头
    if not HEAD_RE.match(lines[lineno - 1]):
        # 行号可能指向条目中间·向前找最近的条目头
        start = lineno
        while start > 1 and not HEAD_RE.match(lines[start - 1]):
            start -= 1
        if not HEAD_RE.match(lines[start - 1]):
            return None
    else:
        start = lineno
    # 找下一个条目头或文末
    end = start
    while end < len(lines):
        if end > start and HEAD_RE.match(lines[end]):
            break
        end += 1
    block = '\n'.join(lines[start - 1:end])
    return block, start, end


class CrossRef:
    def __init__(self, root=None):
        self.root = root or HERE

    def _vol_path(self, vol):
        """按卷名找路径。先按文件名找·找不到报 KeyError。"""
        # 与 daybook.conf 一致：协作卷.txt / 辞海卷.txt 等
        cand = os.path.join(self.root, vol + '.txt')
        if os.path.exists(cand):
            return cand
        cand = os.path.join(self.root, 'sample', vol + '.txt')
        if os.path.exists(cand):
            return cand
        raise KeyError('卷 %s 不存在' % vol)

    def _entry_hash(self, text, lineno):
        """算条目 SHA-256 前 8 位（hex）。"""
        r = _entry_at(text, lineno)
        if not r:
            return None
        block, _, _ = r
        return hashlib.sha256(block.encode('utf-8')).hexdigest()[:8]

    def make_ref(self, vol, lineno):
        """生成引用 [卷名#L行号-SHA256前8位]。"""
        path = self._vol_path(vol)
        text = _read_text(path)
        h = self._entry_hash(text, lineno)
        if not h:
            raise KeyError('行 %d 无条目' % lineno)
        return '[%s#L%d-%s]' % (vol, lineno, h)

    def resolve(self, vol, lineno):
        """读条目原文。返回 (块文本, 起始行, 末尾行) 或 None。"""
        path = self._vol_path(vol)
        text = _read_text(path)
        return _entry_at(text, lineno)

    def verify(self, vol, lineno, sha_prefix=None):
        """校验 hash·不指定 sha_prefix 则自算自比（条目存在即通过）。
        指定 sha_prefix 则 hash 不匹配报 False（条目被篡改）。"""
        path = self._vol_path(vol)
        text = _read_text(path)
        cur = self._entry_hash(text, lineno)
        if cur is None:
            return False
        if sha_prefix and cur != sha_prefix:
            return False
        return True

    def parse(self, ref_str):
        """解析引用字符串·返回 (卷名, 行号, sha前8位)。"""
        m = REF_RE.search(ref_str)
        if not m:
            return None
        return m.group(1), int(m.group(2)), m.group(3)

    def verify_ref(self, ref_str):
        """完整校验引用·parse + verify。返回 True/False。"""
        p = self.parse(ref_str)
        if not p:
            return False
        vol, lineno, sha = p
        return self.verify(vol, lineno, sha)

    def find_backrefs(self, target_vol, target_lineno, vols=None):
        """扫所有卷·找出引用 (target_vol, target_lineno) 的地方。
        vols 可指定·默认扫 root 顶层 .txt 卷。"""
        ref_str = '#L%d-' % target_lineno  # 子串预过滤·命中再做正则（性能+消 dead code）
        results = []
        if vols is None:
            vols = []
            for f in os.listdir(self.root):
                if f.endswith('.txt') and os.path.isfile(os.path.join(self.root, f)):
                    vols.append(f[:-4])
            sample_dir = os.path.join(self.root, 'sample')
            if os.path.isdir(sample_dir):
                for f in os.listdir(sample_dir):
                    if f.endswith('.txt') and os.path.isfile(os.path.join(sample_dir, f)):
                        vols.append(f[:-4])
        for vol in vols:
            try:
                path = self._vol_path(vol)
            except KeyError:
                continue
            text = _read_text(path)
            lines = text.split('\n')
            cur_lineno = 0
            for i, line in enumerate(lines, 1):
                if HEAD_RE.match(line):
                    cur_lineno = i
                # 匹配 [target_vol#Ltarget_lineno-...]·先子串预过滤再正则
                if ref_str in line and re.search(r'\[%s#L%d-[0-9a-f]{8}\]' % (re.escape(target_vol), target_lineno), line):
                    results.append((vol, cur_lineno, line))
        return results


def main():
    import sys
    if len(sys.argv) < 2:
        print(__doc__); return 1
    cr = CrossRef()
    cmd = sys.argv[1]
    if cmd == 'make' and len(sys.argv) >= 4:
        print(cr.make_ref(sys.argv[2], int(sys.argv[3])))
    elif cmd == 'resolve' and len(sys.argv) >= 4:
        r = cr.resolve(sys.argv[2], int(sys.argv[3]))
        if r:
            print(r[0])
        else:
            print('（无条目）')
    elif cmd == 'verify' and len(sys.argv) >= 4:
        sha = sys.argv[4] if len(sys.argv) >= 5 else None
        print('verify: %s' % ('PASS' if cr.verify(sys.argv[2], int(sys.argv[3]), sha) else 'FAIL'))
    elif cmd == 'parse' and len(sys.argv) >= 3:
        print(cr.parse(sys.argv[2]))
    elif cmd == 'backrefs' and len(sys.argv) >= 4:
        for vol, ln, line in cr.find_backrefs(sys.argv[2], int(sys.argv[3])):
            print('%s#L%d: %s' % (vol, ln, line))
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
