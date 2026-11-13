#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""MCP Server（W-DB-023-G2·第 5 项·修复版 r2）
MCP Server (W-DB-023-G2 · Item 5 · fix revision r2)
================================================
对照审核报告修复：
Fixes applied against the review report:
- 加 resources/subscribe + resources/unsubscribe 方法（P1+）
- Added the resources/subscribe + resources/unsubscribe methods (P1+)
- 删 shutdown（P2-2·LSP 遗留·MCP 无此方法）
- Removed shutdown (P2-2 · an LSP leftover · MCP has no such method)
- initialize 协商客户端 protocolVersion（P2-5）
- initialize negotiates the client protocolVersion (P2-5)
- tools/call 透传 agent_id+signature 给 mcp_tools.call_tool（P1-1）
- tools/call passes agent_id+signature through to mcp_tools.call_tool (P1-1)
- resources/read 透传 agent_id 给 mcp_resources.read_resource（P1-2）
- resources/read passes agent_id through to mcp_resources.read_resource (P1-2)
- tools/call 失败返 isError:true 已在 mcp_tools 处理·server 不再兜成 -32603（P2-1）
- tools/call failure returning isError:true is handled in mcp_tools · the server no longer falls back to -32603 (P2-1)
- 零依赖：仅 Python 3 标准库
- Zero dependencies: Python 3 standard library only
"""
import sys, os, json

# 彻底零写盘：本次进程不生成 __pycache__（必须在 import 本地模块之前设置）。
# Zero disk writes: never emit __pycache__ in this process (must be set before importing local modules).
sys.dont_write_bytecode = True
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcp_transport as tr
import mcp_resources as res
import mcp_tools as tools
import mcp_prompts as prompts
from mcp_subscribe import MANAGER as SUBS

def _suite_version():
    """套件版本：取 pack.py 的单一真相源 —— 先读同目录 version.txt（打包器写入），
    再回退解析同目录 pack.py 的 SUITE_VERSION；都没有则 '0.0.0'。
    Suite version: single source of truth in pack.py — read sibling version.txt (written by the packer) first,
    then fall back to parsing SUITE_VERSION from a sibling pack.py; '0.0.0' if neither exists.
    """
    try:
        with open(os.path.join(HERE, 'version.txt'), encoding='utf-8') as fh:
            first = fh.readline()
        return first.split('v', 1)[1].split()[0]
    except (OSError, IndexError):
        pass
    try:
        with open(os.path.join(HERE, 'pack.py'), encoding='utf-8') as fh:
            for line in fh:
                if line.strip().startswith('SUITE_VERSION'):
                    return line.split('=', 1)[1].strip().strip('\'"')
    except OSError:
        pass
    return '0.0.0'


SERVER_INFO = {
    'name': 'daybook-mcp',
    'version': _suite_version(),  # 单一真相源：pack.py / version.txt（不再手改两处）
}
PROTOCOL_VERSION = '2024-11-05'  # MCP 协议版本 · MCP protocol version
CAPABILITIES = {
    'resources': {'listChanged': True, 'subscribe': True},
    'tools': {'listChanged': False},
    'prompts': {'listChanged': False},
}


def handle_initialize(params):
    """P2-5：协商 protocolVersion。
    P2-5: negotiate protocolVersion.
    客户端 params.protocolVersion 我们不支持则仍返回我们自己的版本·客户端自行决定是否继续。
    If the client's params.protocolVersion is unsupported we still return our own version · the client decides whether to continue.
    """
    client_pv = params.get('protocolVersion') if params else None
    # 我们只支持一个版本·不降级·直接返回
    # We support only one version · no downgrade · return directly
    # （多版本时此处可加 if client_pv == 'xxx': return matched_pv）
    # (With multiple versions you could add here: if client_pv == 'xxx': return matched_pv)
    return {
        'protocolVersion': PROTOCOL_VERSION,
        'capabilities': CAPABILITIES,
        'serverInfo': SERVER_INFO,
    }


def dispatch(msg, push_callable=None):
    """dispatch 一条 request·返回 response 或 None（notification）。
    Dispatch one request · return a response or None (notification).
    push_callable 用于 subscribe 时回推·None 表示无回推通道。
    push_callable is used to push back on subscribe · None means no push channel.
    """
    if not tr.is_request(msg):
        return None
    if tr.is_notification(msg):
        # notifications/initialized 等无 id 消息·按 spec 不回响应
        # Messages without an id such as notifications/initialized · per spec no response is sent
        return None
    req_id = tr.get_id(msg)
    method = tr.get_method(msg)
    params = tr.get_params(msg) or {}

    # 提取 _meta.agent_id/signature（MCP 惯例：_meta 字段携带调用方身份）
    # Extract _meta.agent_id/signature (MCP convention: the _meta field carries the caller identity)
    meta = params.get('_meta') if isinstance(params, dict) else None
    agent_id = meta.get('agentId') if meta else None
    signature = meta.get('signature') if meta else None
    # 客户端未在 _meta 携带身份时，用启动配置里的 DAYBOOK_AGENT_ID 兜底（只影响审计署名）
    # When the client omits _meta identity, fall back to DAYBOOK_AGENT_ID from the launch config (audit label only)
    if not agent_id:
        agent_id = (os.environ.get('DAYBOOK_AGENT_ID') or '').strip() or None

    try:
        if method == 'initialize':
            result = handle_initialize(params)
        elif method == 'resources/list':
            result = {'resources': res.list_resources()}
        elif method == 'resources/read':
            uri = params.get('uri')
            if not uri:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 uri')
            r = res.read_resource(uri, params.get('offset'), params.get('limit'),
                                  agent_id=agent_id)
            if r is None:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '卷不存在或非法：%s' % uri)
            result = {'contents': [r]}
        elif method == 'resources/subscribe':
            # P1+：订阅指定 uri·文件变 → push notifications/resources/updated
            # P1+: subscribe to the given uri · on file change → push notifications/resources/updated
            uri = params.get('uri')
            if not uri:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 uri')
            # 先校验资源真实存在·不存在就报错（不许返回假的 subscribed:True）
            # Validate the resource really exists first · error when absent (never a fake subscribed:True)
            if not res.resource_exists(uri):
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '资源不存在：%s' % uri)
            if push_callable is None:
                raise tr.RPCError(tr.ERR_INTERNAL_ERROR, '此通道不支持 push（subscribe 需双向通道）')
            ok = SUBS.subscribe(uri, push_callable)
            result = {'subscribed': True, 'uri': uri, 'new': ok}
        elif method == 'resources/unsubscribe':
            uri = params.get('uri')
            if not uri:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 uri')
            if push_callable is None:
                raise tr.RPCError(tr.ERR_INTERNAL_ERROR, '此通道不支持 push')
            ok = SUBS.unsubscribe(uri, push_callable)
            result = {'unsubscribed': ok, 'uri': uri}
        elif method == 'tools/list':
            result = {'tools': tools.list_tools()}
        elif method == 'tools/call':
            name = params.get('name')
            args = params.get('arguments') or {}
            if not name:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 name')
            # P1-1：透传 agent_id+signature 给 mcp_tools
            # P1-1: pass agent_id+signature through to mcp_tools
            result = tools.call_tool(name, args, agent_id=agent_id, signature=signature)
            # tools.call_tool 失败返 isError:true·server 不再兜成 -32603（P2-1）
            # tools.call_tool returns isError:true on failure · the server no longer falls back to -32603 (P2-1)
            # 直接 wrap result·success 路径也是 result 字段
            # Wrap result directly · the success path also uses the result field
            # 注意：MCP 协议规定 tools/call 返回 CallToolResult·放 result 字段即可
            # Note: the MCP protocol specifies tools/call returns a CallToolResult · placing it in the result field suffices
        elif method == 'prompts/list':
            result = {'prompts': prompts.list_prompts()}
        elif method == 'prompts/get':
            name = params.get('name')
            args = params.get('arguments') or {}
            if not name:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 name')
            result = prompts.get_prompt(name, args)
        elif method == 'ping':
            result = {}
        else:
            return tr.make_error(req_id, tr.ERR_METHOD_NOT_FOUND,
                                 'method not found: %s' % method)
        return tr.make_result(req_id, result)

    except tr.RPCError as e:
        return tr.make_error(req_id, e.code, e.message, e.data)
    except res.RootError as e:
        # 读错根必须报错·不许静默返回空资源
        # A wrong root must fail loudly · never return resources as an empty list
        return tr.make_error(req_id, tr.ERR_INTERNAL_ERROR,
                             '账本根目录不可用：%s' % e)
    except ValueError as e:
        return tr.make_error(req_id, tr.ERR_INVALID_PARAMS, str(e))
    except Exception as e:
        return tr.make_error(req_id, tr.ERR_INTERNAL_ERROR,
                            'internal error: %s' % type(e).__name__,
                            str(e))


def serve(infile=None, outfile=None):
    """主循环·从 infile 读·写 outfile。
    Main loop · read from infile · write to outfile.
    outfile 用于回推 response 和 push notifications/resources/updated。
    outfile is used to push back responses and push notifications/resources/updated.
    """
    infile = infile or sys.stdin
    outfile = outfile or sys.stdout

    def push(msg):
        """subscribe 回调·把 notifications/resources/updated 写到 outfile。
        subscribe callback · write notifications/resources/updated to outfile.
        """
        try:
            tr.write_message(outfile, msg)
        except Exception:
            pass

    for line in infile:
        msg, err = tr.decode_frame(line)
        if err is not None:
            tr.write_message(outfile, err)
            continue
        if msg is None:
            continue
        if isinstance(msg, dict):
            resp = dispatch(msg, push_callable=push)
            if resp is not None:
                tr.write_message(outfile, resp)
                # 客户端断连特征：写失败 → 清掉它的订阅
                # Client-disconnect signal: write failed → clear its subscriptions
                if 'error' in resp and resp['error']['code'] == tr.ERR_INTERNAL_ERROR \
                        and 'broken pipe' in str(resp['error'].get('data', '')).lower():
                    SUBS.unsubscribe_all(push)
        elif isinstance(msg, list):
            out = []
            for m in msg:
                if not isinstance(m, dict):
                    out.append(tr.make_error(None, tr.ERR_INVALID_REQUEST,
                                              'invalid request in batch'))
                    continue
                resp = dispatch(m, push_callable=push)
                if resp is not None:
                    out.append(resp)
            if out:
                tr.write_message(outfile, out)


def main():
    """启动自检后进主循环。根无效 → stderr 报错并退出（不静默空跑）。
    Run the startup self-check, then enter the main loop. An invalid root → stderr error and exit (never silently serve an empty ledger)."""
    try:
        root, nvol = res.self_check()
    except res.RootError as e:
        sys.stderr.write('[daybook-mcp] FATAL 启动自检失败：%s\n' % e)
        sys.stderr.flush()
        raise SystemExit(2)
    sys.stderr.write('[daybook-mcp] root=%s volumes=%d\n' % (root, nvol))
    sys.stderr.flush()
    serve()


if __name__ == '__main__':
    main()
