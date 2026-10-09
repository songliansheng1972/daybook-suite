#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Prompts（W-DB-023-G2·第 4 项）
================================================
- 暴露 daybook 模板 prompts
- prompts/list：列所有 prompt
- prompts/get：取 prompt 内容（按参数填充模板）
- 模板用 {占位符} 风格·str.format
- 零依赖：仅用 Python 3 标准库
"""

# Prompt 模板清单
PROMPTS = [
    {
        'name': 'daily_journal',
        'description': '生成今日日志模板·按 [时间] [标签] [子标签] [作者] 内容 格式',
        'arguments': [
            {'name': 'author', 'description': '作者', 'required': True},
            {'name': 'tag', 'description': '主标签', 'required': True},
            {'name': 'topic', 'description': '主题概要', 'required': False},
        ],
        'template': (
            '请按 daybook 格式生成今日日志条目：\n'
            '格式：[YYYY-MM-DD HH:MM] [{tag}] [{subtag}] [{author}] 内容\n'
            '主题：{topic}\n'
            '要求：\n'
            '1. 时间用当前北京时间\n'
            '2. 子标签按主题细分（如 MCP/Agent/索引）\n'
            '3. 内容简练·一行一条·append-only\n'
            '4. 不要修改历史条目\n'
        ),
    },
    {
        'name': 'weekly_review',
        'description': '周回顾·从指定卷里抽出本周条目做总结',
        'arguments': [
            {'name': 'volume', 'description': '卷名', 'required': True},
            {'name': 'week', 'description': '周次（YYYY-Www）', 'required': False},
        ],
        'template': (
            '请对 {volume} 卷做周回顾：\n'
            '周次：{week}（省略则本周）\n'
            '要求：\n'
            '1. 用 daybook_query 工具拉取本周所有条目\n'
            '2. 按标签分组统计\n'
            '3. 找出本周高频主题与异常事件\n'
            '4. 输出 ≤ 5 行总结\n'
        ),
    },
    {
        'name': 'cross_ref_audit',
        'description': '审计跨卷引用·扫所有引用并校验完整性',
        'arguments': [
            {'name': 'volume', 'description': '起始卷名', 'required': True},
        ],
        'template': (
            '请审计 {volume} 卷里的跨卷引用：\n'
            '步骤：\n'
            '1. 用 cross_ref 解析所有 [卷名#L行-SHA8] 模式\n'
            '2. 对每个引用调 cross_ref_verify\n'
            '3. 列出所有失败的引用（hash 不匹配或行不存在）\n'
            '4. 输出审计报告·含失败数/总数/失败明细\n'
        ),
    },
    {
        'name': 'agent_handover',
        'description': 'Agent 交接模板·按 W-DB-013 范式生成交接记录',
        'arguments': [
            {'name': 'from_agent', 'description': '原施方', 'required': True},
            {'name': 'to_agent', 'description': '接手方', 'required': True},
            {'name': 'task', 'description': '工单号', 'required': True},
        ],
        'template': (
            '请生成 Agent 交接记录（W-DB-013 范式）：\n'
            '原施方：{from_agent}\n'
            '接手方：{to_agent}\n'
            '工单：{task}\n'
            '要求：\n'
            '1. 协作卷追加 [事件] 条目记录交接\n'
            '2. 标注原施方未完成项与已交接项\n'
            '3. 接手方声明按现状基线施工\n'
        ),
    },
]


def list_prompts():
    """列所有 prompt·schema 风格。"""
    out = []
    for p in PROMPTS:
        out.append({
            'name': p['name'],
            'description': p['description'],
            'arguments': p['arguments'],
        })
    return out


def get_prompt(name, args=None):
    """取 prompt 内容·args 是 dict·按 template 填充。"""
    args = args or {}
    for p in PROMPTS:
        if p['name'] == name:
            # 校验 required
            for a in p['arguments']:
                if a.get('required') and a['name'] not in args:
                    raise ValueError('缺少必填参数：%s' % a['name'])
            # 填充模板·缺失的占位符用空串
            tpl = p['template']
            # 收集所有 {xxx} 占位符
            import re
            keys = set(re.findall(r'\{(\w+)\}', tpl))
            fill = {k: args.get(k, '') for k in keys}
            try:
                text = tpl.format(**fill)
            except (KeyError, IndexError):
                text = tpl
            return {
                'description': p['description'],
                'messages': [
                    {'role': 'user', 'content': {'type': 'text', 'text': text}},
                ],
            }
    raise ValueError('未知 prompt：%s' % name)
