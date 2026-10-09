#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daybook · HOOK-A 选择性追更（daybook 3.0）
原理：扫对话卷新条目，关键词命中即追更到目标卷。
设计纪律（老宋定）：
  - 纯文本：关键词表 = txt，可 cat 查
  - 零依赖：只用标准库 re
  - 白盒：触发规则全可见
  - 用户主权：关键词表用户可改
  - 作者 ID 红线：每条追更带作者
  - 来源可追：每条带对话卷来源行号
  - 防过度追更：同一条对话只追更一次（按对话卷行号去重）
用法：
  python3 daybook_hook.py [对话卷] [关键词表]
  默认: 对话卷.txt + hook_a_关键词.txt
"""
import os, sys, re, time, io

# 复用 daybook_append 的原子写
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daybook_append import append_one, get_pipe_buf


def load_keywords(kw_path):
    """加载关键词表。返回 [(目标卷, 类, [关键词]), ...]
    格式：[目标卷] [类] 关键词1|关键词2|...
    """
    if not os.path.exists(kw_path):
        return []
    rules = []
    with io.open(kw_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^\[([^\]]+)\]\s*\[([^\]]+)\]\s*(.+)$', line)
            if not m:
                continue
            vol, kind, kws = m.group(1), m.group(2), m.group(3)
            kws = [k.strip() for k in kws.split('|') if k.strip()]
            rules.append((vol, kind, kws))
    return rules


def scan_block(text, rules):
    """扫描一段文本，返回命中的 (目标卷, 类, 命中关键词) 列表。
    每条对话只取第一个命中的类（防过度追更）。
    """
    hits = []
    for vol, kind, kws in rules:
        for kw in kws:
            # 加边界：不匹配"决定性"中的"决定"
            # 用 \b 在中文环境下不可靠，改用：前后非字符边界
            pat = r'(?<![\w])' + re.escape(kw) + r'(?![\w])'
            if re.search(pat, text):
                hits.append((vol, kind, kw))
                break  # 该类命中一次即停
        if hits:
            break  # 第一个类命中即停（防过度追更）
    return hits


def parse_dialog(dialog_path, root='.'):
    """解析对话卷，返回 [(行号, 时间, 类, 标题, 作者, 正文)]
    对话卷格式：每条登记了原件路径 + SHA-256。
    HOOK-A 要扫的是原件文件的内容，不是对话卷的登记条目。
    兼容 3 段（无作者）和 4 段（带作者）格式。
    """
    if not os.path.exists(dialog_path):
        return []
    from safeio import read_vol
    txt, _enc, _why = read_vol(dialog_path)
    head_re = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')
    # 对话卷条目格式：[时间] [类] [标题] [作者] 对话原件/xxx.txt\nSHA256: ...
    blocks = []
    cur_line = None
    cur_start = 0
    cur_text = ''
    cur_meta = None  # (类, 标题, 作者, 原件路径)
    ln = 0
    for line in txt.split('\n'):
        ln += 1
        if head_re.match(line):
            if cur_line is not None:
                blocks.append((cur_start, cur_text, cur_meta))
            cur_line = line
            cur_start = ln
            cur_text = line
            # 解析 [时间][类][标题][作者] 对话原件/xxx.txt
            tag_re = re.compile(r'^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\](?:\s*\[([^\]]*)\])?\s*(对话原件/[^\s]+\.txt)')
            m = tag_re.match(line)
            if m:
                cur_meta = (m.group(1), m.group(2), m.group(3) or '未标', m.group(4))
            else:
                cur_meta = None
        elif cur_line is not None:
            cur_text += '\n' + line
    if cur_line is not None:
        blocks.append((cur_start, cur_text, cur_meta))
    return blocks


def load_processed(record_path):
    """加载已处理行号集合，防重复追更。"""
    if not os.path.exists(record_path):
        return set()
    with io.open(record_path, encoding='utf-8') as f:
        return set(int(x.strip()) for x in f if x.strip())


def mark_processed(record_path, line_no):
    """标记行号已处理。append-only。"""
    with io.open(record_path, 'a', encoding='utf-8') as f:
        f.write('%d\n' % line_no)


def run(dialog_path, kw_path, root='.'):
    """HOOK-A 主流程：扫对话卷登记的原件内容 → 关键词命中 → 追更到目标卷。"""
    rules = load_keywords(kw_path)
    if not rules:
        print('关键词表为空：%s' % kw_path)
        return 1
    print('加载 %d 条规则' % len(rules))

    blocks = parse_dialog(dialog_path, root)
    if not blocks:
        print('对话卷为空：%s' % dialog_path)
        return 1
    print('对话卷 %d 条' % len(blocks))

    record_path = os.path.join(root, '.hook_a_已处理.txt')
    processed = load_processed(record_path)

    new_blocks = [(ln, t, m) for ln, t, m in blocks if ln not in processed]
    print('新条目 %d 条（已处理 %d 条）' % (len(new_blocks), len(processed)))
    if not new_blocks:
        print('无新条目，跳过。')
        return 0

    n_hit = 0
    for ln, _dialog_text, meta in new_blocks:
        if not meta:
            mark_processed(record_path, ln)
            continue
        kind, title, author, orig_path = meta
        full_orig = os.path.join(root, orig_path)
        if not os.path.exists(full_orig):
            print('  ★ 原件不存在：%s' % orig_path)
            mark_processed(record_path, ln)
            continue
        with io.open(full_orig, encoding='utf-8') as f:
            orig_text = f.read()
        hits = scan_block(orig_text, rules)
        if not hits:
            mark_processed(record_path, ln)
            continue
        target_vol, target_kind, kw = hits[0]
        target_path = os.path.join(root, '%s卷.txt' % target_vol)
        msg = 'HOOK-A 追更·来源 对话卷 行=%d·原件=%s·命中「%s」\n%s' % (
            ln, orig_path, kw, orig_text.rstrip()[:100])  # 截 100 字防超 512B
        rc = append_one(target_path, target_kind, 'HOOK-A 追更', msg, author=author)
        if rc == 0:
            mark_processed(record_path, ln)
            n_hit += 1
            print('  追更 → %s卷 [类=%s 作者=%s 关键词=%s]' % (target_vol, target_kind, author, kw))
        else:
            print('  ★ 追更失败（rc=%d）行=%d 超长?' % (rc, ln))

    print('追更完成：%d 条' % n_hit)
    return 0


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    dialog_path = sys.argv[1] if len(sys.argv) >= 3 else os.path.join(root, '对话卷.txt')
    kw_path = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(root, 'hook_a_关键词.txt')
    if not os.path.exists(dialog_path):
        print('对话卷不存在：%s' % dialog_path)
        return 1
    if not os.path.exists(kw_path):
        print('关键词表不存在：%s' % kw_path)
        return 1
    print('=== HOOK-A 选择性追更 ===')
    print('对话卷: %s' % dialog_path)
    print('关键词表: %s' % kw_path)
    print('---')
    return run(dialog_path, kw_path, root)


if __name__ == '__main__':
    sys.exit(main())
