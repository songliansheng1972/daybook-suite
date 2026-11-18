#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""种子化生成器：const / random / shuffle 三模式（步骤 5）
Seeded generator: const / random / shuffle (step 5)
================================================
属性层不新增手写用例，边角（别名拼写、路径段、并发条目）由本模块按种子生成：
  const   固定取值，便于逐字复现失败；
  random  rng 抽样，覆盖更宽；
  shuffle 固定取值池按种子洗牌，顺序变化而取值可控。
失败时可一键复现：run_all.py 会打印 `--seed` / `--mode`，原样重跑即可。
"""
import random

MODES = ('const', 'random', 'shuffle')

_CONST_SEGS = ('sub', '甲', 'b')
_CONST_TITLES = ('alpha', '标题', '第二条')
_CONST_CATS = ('测试', '实验', '记录')


class Gen:
    """确定性生成器：同一个 (seed, mode) 永远给出同一串值。
    Deterministic generator: one (seed, mode) always yields the same sequence."""

    def __init__(self, seed=7, mode='const'):
        if mode not in MODES:
            raise ValueError('未知模式 %r（只支持 %s）' % (mode, ', '.join(MODES)))
        self.seed = int(seed)
        self.mode = mode
        self.rng = random.Random(self.seed)

    def _pick(self, i, pool, prefix):
        if self.mode == 'const':
            return pool[i % len(pool)]
        if self.mode == 'random':
            return '%s%d' % (prefix, self.rng.randrange(10000))
        return pool[i % len(pool)]

    def segs(self, n=2):
        """生成 n 个合法路径段（无分隔符、无 . / ..）。"""
        return tuple(self._pick(i, _CONST_SEGS, 'seg')
                     for i in range(n))

    def title(self, i):
        return self._pick(i, _CONST_TITLES, 'title')

    def category(self, i):
        return self._pick(i, _CONST_CATS, 'cat')

    def order(self, items):
        """const 原序；shuffle 按种子洗牌；random 先洗牌再抽样（长度不变）。"""
        items = list(items)
        if self.mode == 'const':
            return items
        if self.mode == 'shuffle':
            out = list(items)
            self.rng.shuffle(out)
            return out
        out = list(items)
        self.rng.shuffle(out)
        return out

    def entry(self, i, author='皮特'):
        """一条合法账目（时间唯一，正文带序号，便于查重/查丢更新）。"""
        return '[2026-11-13 10:%02d:%02d] [%s] [%s] [%s] 正文-%04d\n' % (
            (i // 60) % 60, i % 60, self.category(i), self.title(i), author, i)

    def entries(self, n):
        return [self.entry(i) for i in range(n)]


def for_seed(seed=7, mode='const'):
    return Gen(seed, mode)


if __name__ == '__main__':
    import sys
    g = for_seed(int(sys.argv[1]) if len(sys.argv) > 1 else 7,
                 sys.argv[2] if len(sys.argv) > 2 else 'const')
    print('seed=%d mode=%s' % (g.seed, g.mode))
    print('segs=%r' % (g.segs(3),))
    for line in g.entries(3):
        print(line.rstrip())
