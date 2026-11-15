#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 0 的写事件夹具：只覆盖登记表里列出的写点。
Step-0 write-event fixture: exercises exactly the write sites in the registry."""
import os


def run(root, conf_path):
    import safeio
    p = os.path.join(root, 'vol.txt')
    # 夹具自建卷（唯一的非 safeio 直写；登记为 ('run','vol.txt')）
    open(p, 'wb').write(b'a\n')
    safeio.atomic_append(p, b'b\n', root=root)
    with safeio.locked(root):
        safeio.append_inplace(p, b'c\n', root=root)
    safeio.atomic_write(p, b'd\n', root=root)
    safeio.read_modify_write(p, lambda b: b + b'e\n', root=root)
