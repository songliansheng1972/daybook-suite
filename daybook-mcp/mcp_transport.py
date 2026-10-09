#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP 传输层（W-DB-023-G2·第 1 项）
================================================
- JSON-RPC 2.0 over newline-delimited stdio
- 解码：读 stdin → 切行 → JSON.loads
- 编码：JSON.dumps + '\n' → 写 stdout
- 错误码（JSON-RPC 2.0 标准）：
  -32700 parse error
  -32600 invalid request
  -32601 method not found
  -32602 invalid params
  -32603 internal error
- 零依赖：仅用 Python 3 标准库（sys/json）
"""
import sys, json

# JSON-RPC 2.0 错误码
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
    """构造 JSON-RPC error response。req_id=None 表示 notification 或解析失败。"""
    return {
        'jsonrpc': '2.0',
        'id': req_id,
        'error': {'code': code, 'message': message, 'data': data} if data else
                 {'code': code, 'message': message},
    }


def make_result(req_id, result):
    """构造 JSON-RPC success response。"""
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def decode_frame(line):
    """解一行 JSON-RPC。返回 (msg, error_or_None)。
    - 单个 dict：request/response
    - list：batch（本实现不展开 batch·返回原 list 由 caller 决定）
    - 解析失败返回 (None, error_response)"""
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
    """msg → JSON + '\n' str。"""
    return json.dumps(msg, ensure_ascii=False) + '\n'


def read_messages(infile):
    """生成器：从 file-like 读消息·yield (msg, error)。"""
    for line in infile:
        msg, err = decode_frame(line)
        if msg is not None or err is not None:
            yield msg, err


def is_request(msg):
    """判断是 request（有 method 字段）还是 response。"""
    return isinstance(msg, dict) and 'method' in msg


def is_notification(msg):
    """notification：request 但无 id。"""
    return is_request(msg) and 'id' not in msg


def get_id(msg):
    """取 id·notification 返回 None。"""
    return msg.get('id') if isinstance(msg, dict) else None


def get_method(msg):
    return msg.get('method') if isinstance(msg, dict) else None


def get_params(msg):
    """params 可以是 list 或 dict·None 表示缺省。"""
    if not isinstance(msg, dict):
        return None
    return msg.get('params', None)


def write_message(outfile, msg):
    """写一条 JSON-RPC 消息到 stdout。"""
    outfile.write(encode_frame(msg))
    outfile.flush()


def write_error(outfile, req_id, code, message, data=None):
    write_message(outfile, make_error(req_id, code, message, data))


def write_result(outfile, req_id, result):
    write_message(outfile, make_result(req_id, result))
