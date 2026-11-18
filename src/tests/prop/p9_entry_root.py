#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P9 · 入口级换根（属性层）
P9 · entry-level root swap (property layer)
================================================
Hub 启动时只开一次 Root，把同一句柄交给 TaskVolume / Heartbeat / AgentLock。
根被 rename 走、原路径又建同名目录后，三类写入仍必须落旧 inode；新目录零新增。
变异 M10（TaskVolume 写时把 Root 退回 str(path) 重开）必须让本件变红。
"""
import os
import stat

import common
from common import check


def run(seed=7, mode='const'):
    print('  -- P9 入口级换根（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p9_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        common.stage(root)
        with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write(common.CONF)
        import orchestrator
        hub = orchestrator.Hub(root=root)
        try:
            check('P9 三类 + Registry 共用 Hub 的同一个 Root 句柄',
                  hub.tv.root is hub.root_handle
                  and hub.hb.root is hub.root_handle
                  and hub.lock.root is hub.root_handle
                  and hub.reg.root is hub.root_handle,
                  'tv=%s hb=%s lock=%s reg=%s'
                  % (hub.tv.root is hub.root_handle, hub.hb.root is hub.root_handle,
                     hub.lock.root is hub.root_handle, hub.reg.root is hub.root_handle))
            hub.tv.create('agent_p9', 'before')
            moved = os.path.join(base, 'root_moved')
            os.rename(root, moved)
            os.makedirs(root)

            hub.tv.create('agent_p9', 'after-swap')
            tasks_old = os.path.join(moved, '任务卷.txt')
            tasks_new = os.path.join(root, '任务卷.txt')
            check('P9 TaskVolume 换根后写旧 inode',
                  os.path.exists(tasks_old)
                  and 'after-swap' in open(tasks_old, encoding='utf-8').read()
                  and not os.path.exists(tasks_new),
                  'old=%s new=%s' % (os.path.exists(tasks_old),
                                     os.path.exists(tasks_new)))

            hub.hb.beat('agent_p9')
            hb_old = os.path.join(moved, '心跳卷.txt')
            hb_new = os.path.join(root, '心跳卷.txt')
            check('P9 Heartbeat 换根后写旧 inode',
                  os.path.exists(hb_old) and 'agent_p9' in open(hb_old, encoding='utf-8').read()
                  and not os.path.exists(hb_new),
                  'old=%s new=%s' % (os.path.exists(hb_old), os.path.exists(hb_new)))

            lid = hub.lock.acquire('p9', 'agent_p9')
            if lid:
                hub.lock.release(lid)
            lease_old = os.path.join(moved, '租约卷.txt')
            lease_new = os.path.join(root, '租约卷.txt')
            check('P9 AgentLock 换根后写旧 inode',
                  lid and os.path.exists(lease_old) and not os.path.exists(lease_new),
                  'lease=%r old=%s new=%s' % (lid, os.path.exists(lease_old),
                                              os.path.exists(lease_new)))

            # 新根放一份 0644 注册卷：旧实现按路径 os.chmod 会把它改成 0600。
            # Plant a 0644 registry volume in the new root: the old path-based os.chmod
            # would silently flip it to 0600.
            sentinel = os.path.join(root, '注册卷.txt')
            with open(sentinel, 'w', encoding='utf-8') as f:
                f.write('[2026-11-13 00:00:00] [注册] [ag-newroot] [new-root]\n')
            os.chmod(sentinel, 0o644)
            sentinel_before = open(sentinel, encoding='utf-8').read()

            try:
                hub.reg.register('p9_agent')
                reg_err = ''
            except RuntimeError as exc:
                reg_err = str(exc)
            keys_old = os.path.join(moved, '.daybook_keys')
            keys_new = os.path.join(root, '.daybook_keys')
            reg_old = os.path.join(moved, '注册卷.txt')
            keys_old_ok = os.path.isdir(keys_old) and bool(os.listdir(keys_old))
            reg_old_ok = os.path.exists(reg_old)
            sentinel_mode = stat.S_IMODE(os.stat(sentinel).st_mode)
            sentinel_intact = open(sentinel, encoding='utf-8').read() == sentinel_before
            # 三条独立断言：任一条不成立都能单独定位，不用 not reg_err 短路其它判据。
            # Three independent assertions: each can fail on its own; `not reg_err` never
            # short-circuits the others.
            check('P9 Registry 换根后写旧 inode',
                  not reg_err and keys_old_ok and reg_old_ok,
                  'err=%s keys old=%s reg old=%s'
                  % (reg_err[:80], keys_old_ok, reg_old_ok))
            check('P9 Registry 换根后新根零写入（哨兵内容不变）',
                  not os.path.exists(keys_new) and sentinel_intact,
                  'keys new=%s sentinel intact=%s'
                  % (os.path.exists(keys_new), sentinel_intact))
            check('P9 Registry 换根后新根注册卷模式不变',
                  sentinel_mode == 0o644,
                  'mode=0o%o' % sentinel_mode)
            reg_old_mode = stat.S_IMODE(os.stat(reg_old).st_mode) \
                if os.path.exists(reg_old) else -1
            check('P9 Registry 旧根注册卷收紧为 0600',
                  reg_old_mode == 0o600,
                  'mode=%s' % (('0o%o' % reg_old_mode) if reg_old_mode >= 0 else 'missing'))
        finally:
            hub.root_handle.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
