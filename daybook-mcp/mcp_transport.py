#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""MCP 传输层（W-DB-023-G2·第 1 项）
MCP transport layer (W-DB-023-G2 · Item 1)
================================================
- JSON-RPC 2.0 over newline-delimited stdio（基于换行分隔 stdio 的 JSON-RPC 2.0）
- 解码：读 stdin → 切行 → JSON.loads
- Decode: read stdin → split lines → JSON.loads
- 编码：JSON.dumps + '\n' → 写 stdout
- Encode: JSON.dumps + '\n' → write stdout
- 错误码（JSON-RPC 2.0 标准）：
- Error codes (JSON-RPC 2.0 standard):
  -32700 parse error（解析错误）
  -32600 invalid request（无效请求）
  -32601 method not found（方法不存在）
  -32602 invalid params（参数无效）
  -32603 internal error（内部错误）
- 零依赖：仅用 Python 3 标准库（sys/json）
- Zero dependencies: Python 3 standard library only (sys/json)
"""
import sys, json

# JSON-RPC 2.0 错误码
# JSON-RPC 2.0 error codes
ERR_PARSE_ERROR = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL_ERROR = -32603


class RPCError(Exception):
    def __init__(self, code, message, data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


def make_error(req_id, code, message, data=None):
    """构造 JSON-RPC error response。req_id=None 表示 notification 或解析失败。
    Build a JSON-RPC error response. req_id=None means a notification or a parse failure.
    """
    return {
        'jsonrpc': '2.0',
        'id': req_id,
        'error': {'code': code, 'message': message, 'data': data} if data else
                 {'code': code, 'message': message},
    }


def make_result(req_id, result):
    """构造 JSON-RPC success response。
    Build a JSON-RPC success response.
    """
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def decode_frame(line):
    """解一行 JSON-RPC。返回 (msg, error_or_None)。
    Decode one JSON-RPC line. Returns (msg, error_or_None).
    - 单个 dict：request/response
    - A single dict: request/response
    - list：batch（本实现不展开 batch·返回原 list 由 caller 决定）
    - list: batch (this implementation does not expand batches · returns the raw list for the caller to decide)
    - 解析失败返回 (None, error_response)
    - On parse failure returns (None, error_response)
    """
    line = line.strip()
    if not line:
        return None, None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        return None, make_error(None, ERR_PARSE_ERROR, 'parse error', str(e))
    if isinstance(msg, dict):
        if msg.get('jsonrpc') != '2.0':
            return None, make_error(None, ERR_INVALID_REQUEST, 'invalid request: jsonrpc != 2.0')
        return msg, None
    if isinstance(msg, list):
        if not msg:
            return None, make_error(None, ERR_INVALID_REQUEST, 'invalid request: empty batch')
        return msg, None
    return None, make_error(None, ERR_INVALID_REQUEST, 'invalid request: not object')


def encode_frame(msg):
    """msg → JSON + '\n' str。
    msg → JSON + '\n' str.
    """
    return json.dumps(msg, ensure_ascii=False) + '\n'


def read_messages(infile):
    """生成器：从 file-like 读消息·yield (msg, error)。
    Generator: read messages from a file-like object · yield (msg, error).
    """
    for line in infile:
        msg, err = decode_frame(line)
        if msg is not None or err is not None:
            yield msg, err


def is_request(msg):
    """判断是 request（有 method 字段）还是 response。
    Determine whether it is a request (has a method field) or a response.
    """
    return isinstance(msg, dict) and 'method' in msg


def is_notification(msg):
    """notification：request 但无 id。
    notification: a request without an id.
    """
    return is_request(msg) and 'id' not in msg


def get_id(msg):
    """取 id·notification 返回 None。
    Get the id · returns None for a notification.
    """
    return msg.get('id') if isinstance(msg, dict) else None


def get_method(msg):
    return msg.get('method') if isinstance(msg, dict) else None


def get_params(msg):
    """params 可以是 list 或 dict·None 表示缺省。
    params may be a list or a dict · None means absent.
    """
    if not isinstance(msg, dict):
        return None
    return msg.get('params', None)


def write_message(outfile, msg):
    """写一条 JSON-RPC 消息到 stdout。
    Write one JSON-RPC message to stdout.
    """
    outfile.write(encode_frame(msg))
    outfile.flush()


def write_error(outfile, req_id, code, message, data=None):
    write_message(outfile, make_error(req_id, code, message, data))


def write_result(outfile, req_id, result):
    write_message(outfile, make_result(req_id, result))
