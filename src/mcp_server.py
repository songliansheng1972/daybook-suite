#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Server（W-DB-023-G2·第 5 项·修复版 r2）
================================================
对照审核报告修复：
- 加 resources/subscribe + resources/unsubscribe 方法（P1+）
- 删 shutdown（P2-2·LSP 遗留·MCP 无此方法）
- initialize 协商客户端 protocolVersion（P2-5）
- tools/call 透传 agent_id+signature 给 mcp_tools.call_tool（P1-1）
- resources/read 透传 agent_id 给 mcp_resources.read_resource（P1-2）
- tools/call 失败返 isError:true 已在 mcp_tools 处理·server 不再兜成 -32603（P2-1）
- 零依赖：仅 Python 3 标准库
"""
import sys, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcp_transport as tr
import mcp_resources as res
import mcp_tools as tools
import mcp_prompts as prompts
from mcp_subscribe import MANAGER as SUBS

SERVER_INFO = {
    'name': 'daybook-mcp',
    'version': '1.8.1',  # 修复版 r2
}
PROTOCOL_VERSION = '2024-11-05'  # MCP 协议版本
CAPABILITIES = {
    'resources': {'listChanged': True, 'subscribe': True},
    'tools': {'listChanged': False},
    'prompts': {'listChanged': False},
}


def handle_initialize(params):
    """P2-5：协商 protocolVersion。
    客户端 params.protocolVersion 我们不支持则仍返回我们自己的版本·客户端自行决定是否继续。"""
    client_pv = params.get('protocolVersion') if params else None
    # 我们只支持一个版本·不降级·直接返回
    # （多版本时此处可加 if client_pv == 'xxx': return matched_pv）
    return {
        'protocolVersion': PROTOCOL_VERSION,
        'capabilities': CAPABILITIES,
        'serverInfo': SERVER_INFO,
    }


def dispatch(msg, push_callable=None):
    """dispatch 一条 request·返回 response 或 None（notification）。
    push_callable 用于 subscribe 时回推·None 表示无回推通道。"""
    if not tr.is_request(msg):
        return None
    if tr.is_notification(msg):
        # notifications/initialized 等无 id 消息·按 spec 不回响应
        return None
    req_id = tr.get_id(msg)
    method = tr.get_method(msg)
    params = tr.get_params(msg) or {}

    # 提取 _meta.agent_id/signature（MCP 惯例：_meta 字段携带调用方身份）
    meta = params.get('_meta') if isinstance(params, dict) else None
    agent_id = meta.get('agentId') if meta else None
    signature = meta.get('signature') if meta else None

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
            uri = params.get('uri')
            if not uri:
                raise tr.RPCError(tr.ERR_INVALID_PARAMS, '缺 uri')
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
            result = tools.call_tool(name, args, agent_id=agent_id, signature=signature)
            # tools.call_tool 失败返 isError:true·server 不再兜成 -32603（P2-1）
            # 直接 wrap result·success 路径也是 result 字段
            # 注意：MCP 协议规定 tools/call 返回 CallToolResult·放 result 字段即可
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
    except ValueError as e:
        return tr.make_error(req_id, tr.ERR_INVALID_PARAMS, str(e))
    except Exception as e:
        return tr.make_error(req_id, tr.ERR_INTERNAL_ERROR,
                            'internal error: %s' % type(e).__name__,
                            str(e))


def serve(infile=None, outfile=None):
    """主循环·从 infile 读·写 outfile。
    outfile 用于回推 response 和 push notifications/resources/updated。"""
    infile = infile or sys.stdin
    outfile = outfile or sys.stdout

    def push(msg):
        """subscribe 回调·把 notifications/resources/updated 写到 outfile。"""
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
    serve()


if __name__ == '__main__':
    main()
