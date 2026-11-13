#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""跨卷引用（W-DB-023-G3·第 3 项）
Cross-volume references (W-DB-023-G3 · Item 3)
================================================
- 引用格式：[卷名#L行号-SHA256前8位]  如 [协作卷#L1392-a1b2c3d4]
- Reference format: [volume#Lline-first 8 hex of SHA256]  e.g. [协作卷#L1392-a1b2c3d4]
- 解析引用·定位条目原文
- Parse a reference · locate the original entry text
- 校验 SHA-256·防篡改（条目被改 → hash 不匹配 → 报违例）
- Verify SHA-256 · tamper-proof (if the entry is modified → hash mismatch → report a violation)
- 反向引用：扫所有卷找出引用本条目的地方
- Back-references: scan all volumes to find places that reference this entry
- 零依赖：仅用 Python 3 标准库（hashlib/re/os）
- Zero dependencies: Python 3 standard library only (hashlib/re/os)

用法：
Usage:
  from cross_ref import CrossRef
  cr = CrossRef(root='.')
  ref = cr.make_ref('协作卷', 1392)            # 生成引用字符串 · build the reference string
  entry = cr.resolve('协作卷', 1392)          # 读条目原文 · read the entry text
  ok  = cr.verify('协作卷', 1392, 'a1b2c3d4') # 校验 hash（必须给基准）· verify the hash (baseline required)
  backs = cr.find_backrefs('协作卷', 1392)    # 反向引用 · back-references
"""
import os, re, sys, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))

# 引用正则：[卷名#L行号-SHA256前8位]
# Reference regex: [volume#Lline-first 8 hex of SHA256]
REF_RE = re.compile(r'\[([^\[#]+?)#L(\d+)-([0-9a-f]{8})\]')

# 条目头正则（与 daybook.conf 一致·秒可选·编号前缀可选）
# Entry-header regex (consistent with daybook.conf · seconds optional · number prefix optional)
# 两种都要认：`[#83431] [2026-11-13 21:23] …` 与旧式 `[2026-11-13 21:23] …`
# Both forms must match: numbered `[#83431] [2026-11-13 21:23] …` and legacy unnumbered `[2026-11-13 21:23] …`
HEAD_RE = re.compile(r'^(?:\[#\d+\][ ]*)?\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?\]')


def _read_text(path):
    """读卷·自动处理编码·走 safeio.read_vol（统一口径）。
    Read a volume · handle encoding automatically · go through safeio.read_vol (single source of truth).
    """
    from safeio import read_vol
    text, _enc, _why = read_vol(path)
    return text


def _entry_at(text, lineno):
    """取指定起始行号的条目块·单遍扫描·返回 (块文本, 起始行, 末尾行, 是否末条)。
    Fetch the entry block starting at the given line number · single-pass scan · returns
    (block text, start line, end line, is_last).
    lineno 从 1 开始。块边界为「下一个条目头」；其后无头则到文末，is_last=True（调用方须显式标注）。
    lineno is 1-based. The block ends at the next entry head; with no following head it runs to
    EOF and is_last is True (callers must mark it explicitly)."""
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
    # 找下一个条目头或文末（lines[start] 即条目头的下一行·逐行比对）
    # Find the next entry head or EOF (lines[start] is the line right after the head)
    end = start
    while end < len(lines) and not HEAD_RE.match(lines[end]):
        end += 1
    is_last = end >= len(lines)
    block = '\n'.join(lines[start - 1:end])
    return block, start, end, is_last


class CrossRef:
    def __init__(self, root=None):
        self.root = root or HERE

    def _vol_path(self, vol):
        """按卷名找路径。先按文件名找·找不到报 KeyError。
        Find the path by volume name. Look up by filename first · raise KeyError if not found.
        """
        # 与 daybook.conf 一致：协作卷.txt / 语汇卷.txt 等
        # Consistent with daybook.conf: 协作卷.txt / 语汇卷.txt etc.
        cand = os.path.join(self.root, vol + '.txt')
        if os.path.exists(cand):
            return cand
        cand = os.path.join(self.root, 'sample', vol + '.txt')
        if os.path.exists(cand):
            return cand
        raise KeyError('卷 %s 不存在' % vol)

    def _entry_hash(self, text, lineno):
        """算条目 SHA-256 前 8 位（hex）。
        Compute the first 8 hex digits of the entry's SHA-256.
        """
        r = _entry_at(text, lineno)
        if not r:
            return None
        block = r[0]
        return hashlib.sha256(block.encode('utf-8')).hexdigest()[:8]

    def make_ref(self, vol, lineno, index=None):
        """生成引用 [卷名#L行号-SHA256前8位]。
        Build the reference [volume#Lline-first 8 hex of SHA256].
        index 提供时复用调用方（单次 MCP 调用）的整卷索引，整卷只读一次；
        哈希口径不变（条目块 UTF-8 编码后取 SHA-256 前 8 位）。
        When index is given, reuse the caller's (per-MCP-call) whole-volume index so the
        volume is read once; the hash rule is unchanged (SHA-256 of the UTF-8 block, first 8 hex)."""
        path = self._vol_path(vol)
        if index is not None:
            h = index.entry_sha8(path, int(lineno), HEAD_RE)
            if not h:
                raise KeyError('行 %d 无条目' % lineno)
        else:
            text = _read_text(path)
            h = self._entry_hash(text, lineno)
            if not h:
                raise KeyError('行 %d 无条目' % lineno)
        return '[%s#L%d-%s]' % (vol, lineno, h)

    def resolve(self, vol, lineno):
        """读条目原文。返回 (块文本, 起始行, 末尾行, 是否末条) 或 None。
        Read the original entry text. Returns (block text, start line, end line, is_last) or None.
        末条（其后无条目头）is_last=True，块到文末；调用方须显式标注，不许静默延伸。
        For the last entry (no following head) is_last=True and the block runs to EOF;
        callers must mark it explicitly rather than extend silently."""
        path = self._vol_path(vol)
        text = _read_text(path)
        return _entry_at(text, lineno)

    def verify(self, vol, lineno, sha_prefix=None):
        """校验 hash。**必须给基准**：缺基准直接报错，绝不自算自比。
        Verify the hash. **A baseline is mandatory**: missing baseline raises, never self-compares.
        修前不传基准即「条目存在就通过」，对外宣称可校验是硬伤。
        Before, omitting the baseline meant "passes as long as the entry exists" — a hard flaw for a verifier.
        sha_prefix 须为 8 位小写 hex；不匹配返回 False（条目被篡改或基准错）。
        sha_prefix must be 8 lowercase hex chars; a mismatch returns False (entry tampered with, or wrong baseline)."""
        if not sha_prefix:
            raise ValueError('verify 需要基准 SHA8（[卷#L行-SHA8] 的后 8 位）；拒绝无基准自比')
        if not re.match(r'^[0-9a-f]{8}$', sha_prefix):
            raise ValueError('基准 SHA8 格式非法（须 8 位小写 hex）：%r' % (sha_prefix,))
        path = self._vol_path(vol)
        text = _read_text(path)
        cur = self._entry_hash(text, lineno)
        if cur is None:
            return False
        return cur == sha_prefix

    def parse(self, ref_str):
        """解析引用字符串·返回 (卷名, 行号, sha前8位)。
        Parse a reference string · returns (volume name, line number, first 8 hex of sha).
        """
        m = REF_RE.search(ref_str)
        if not m:
            return None
        return m.group(1), int(m.group(2)), m.group(3)

    def verify_ref(self, ref_str):
        """完整校验引用·parse + verify。返回 True/False。
        Fully verify a reference · parse + verify. Returns True/False.
        """
        p = self.parse(ref_str)
        if not p:
            return False
        vol, lineno, sha = p
        return self.verify(vol, lineno, sha)

    def find_backrefs(self, target_vol, target_lineno, vols=None):
        """扫所有卷·找出引用 (target_vol, target_lineno) 的地方。
        Scan all volumes · find places that reference (target_vol, target_lineno).
        vols 可指定·默认扫 root 顶层 .txt 卷。
        vols may be specified · by default scans the top-level .txt volumes under root.
        """
        ref_str = '#L%d-' % target_lineno  # 子串预过滤·命中再做正则（性能+消 dead code） · substring pre-filter, regex only on hits (performance + eliminates dead code)
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
                # Match [target_vol#Ltarget_lineno-...] · substring pre-filter first, then regex
                if ref_str in line and re.search(r'\[%s#L%d-[0-9a-f]{8}\]' % (re.escape(target_vol), target_lineno), line):
                    results.append((vol, cur_lineno, line))
        return results


def main():
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
            if r[3]:
                print('（末条·至文末）')
        else:
            print('（无条目）')
    elif cmd == 'verify' and len(sys.argv) >= 4:
        if len(sys.argv) < 5:
            sys.stderr.write('verify 需要基准 SHA8：cross_ref.py verify <卷> <行号> <sha8>\n')
            return 2
        try:
            ok = cr.verify(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        except ValueError as exc:
            sys.stderr.write('%s\n' % exc)
            return 2
        print('verify: %s' % ('PASS' if ok else 'FAIL'))
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
