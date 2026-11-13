#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据：总条数 / 逐条 sha256 / 无交错（每条完整不跨行）/ 无缺号无重号。
Judge for concurrency-and-capacity: count / per-record sha256 / no interleaving /
no missing or duplicate sequence numbers.

--selftest 用四份人造账（干净/交错/缺号/重号）证明判据能红能绿。
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile

import common as C

MAGIC = b'DBBMAN1\n'
MHDR = struct.Struct('<QI32s')
STRUCT_RE = re.compile(
    rb'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[[^\]]+\] \[bench-\d{7}\] \[ag-[0-9a-f]{16}\] '
    rb'\[id=m[0-9a-f]{16}\] \[sig=[0-9a-f]{64}\] SEQ=\d+ PLAN=[0-9a-f]{16}$')


def write_manifest(name, n, writers, agents, start=1, append=False):
    mode = 'ab' if append else 'wb'
    total = 0
    with open(C.manifest_path(name), mode) as f:
        if not append:
            f.write(MAGIC)
        for seq in range(start, start + n):
            wid = C.writer_of(seq, writers, start)
            aid, secret = C.agent_of(wid, agents)
            b = C.record_no_tail(seq, wid, aid, secret).encode('utf-8')
            f.write(MHDR.pack(seq, len(b), hashlib.sha256(b).digest()))
            total += len(b) + 2
    mp = C.manifest_meta(name)
    if append and os.path.exists(mp):
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)
        meta['n'] += n
        meta['expected_bytes'] += total
    else:
        meta = {'name': name, 'n': n, 'writers': writers, 'start': start,
                'expected_bytes': total}
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def iter_records(path, chunk=1 << 20):
    buf = b''
    with open(path, 'rb') as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            buf += data
            parts = buf.split(b'\n\n')
            buf = parts.pop()
            for rec in parts:
                yield rec
    if buf:
        yield b'\x00TAIL'


def judge_file(path, n, manifest_name, sample_verify=0):
    expected = {}
    exp_hashes = []
    with open(C.manifest_path(manifest_name), 'rb') as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise SystemExit('manifest magic 不符')
        while True:
            b = f.read(MHDR.size)
            if not b:
                break
            seq, ln, h = MHDR.unpack(b)
            expected[seq] = (ln, h)
            exp_hashes.append(h)
    exp_hashes.sort()

    actual_hashes = []
    seen = bytearray(n + 1)
    dup, missing_seq, bad_struct, bad_len, seq_bad = [], [], [], [], []
    count = empty_chunk = 0

    for rec in iter_records(path):
        count += 1
        if rec == b'\x00TAIL':
            bad_struct.append({'i': count, 'why': 'tail bytes without final blank line'})
            continue
        if not rec:
            empty_chunk += 1
            continue
        if b'\n' in rec:
            bad_struct.append({'i': count, 'why': 'record spans multiple lines'})
        if not STRUCT_RE.match(rec):
            bad_struct.append({'i': count, 'why': 'structure mismatch'})
        actual_hashes.append(hashlib.sha256(rec).digest())
        m = re.search(rb'SEQ=(\d+) ', rec)
        if not m:
            seq_bad.append({'i': count, 'why': 'no SEQ token'})
            continue
        seq = int(m.group(1))
        if seq < 1 or seq > n:
            seq_bad.append({'i': count, 'seq': seq, 'why': 'out of range'})
            continue
        if seen[seq]:
            dup.append(seq)
        seen[seq] = 1
        if seq in expected and len(rec) != expected[seq][0]:
            bad_len.append({'seq': seq, 'got': len(rec), 'want': expected[seq][0]})

    missing_seq = [s for s in range(1, n + 1) if not seen[s]]
    actual_hashes.sort()

    checks = {
        'count_equals_expected': {'pass': count == n, 'got': count, 'want': n},
        'sha256_multiset_equal': {'pass': actual_hashes == exp_hashes,
                                  'got': len(actual_hashes), 'want': len(exp_hashes)},
        'no_interleave': {'pass': not bad_struct and empty_chunk == 0,
                          'bad_struct': bad_struct[:5], 'bad_struct_n': len(bad_struct),
                          'empty_chunks': empty_chunk},
        'no_missing_or_dup_seq': {'pass': not dup and not missing_seq and not seq_bad,
                                  'dups_n': len(dup), 'dups': dup[:5],
                                  'missing_n': len(missing_seq), 'missing': missing_seq[:5],
                                  'seq_token_bad_n': len(seq_bad), 'seq_token_bad': seq_bad[:5]},
        'record_length_match': {'pass': not bad_len, 'n': len(bad_len), 'examples': bad_len[:5]},
    }
    result = {'file': path, 'file_bytes': os.path.getsize(path), 'n_expected': n,
              'checks': checks, 'pass': all(v['pass'] for v in checks.values())}
    if sample_verify:
        result['signature_sample'] = verify_sample(path, n, sample_verify)
        result['pass'] = result['pass'] and result['signature_sample']['pass']
    return result


def verify_sample(path, n, k):
    """抽查 k 条，用 orch 自己的 entry_auth 验签（异源判据，防规格互捧）。
    注意：registry 在 ROOT_ORCH，故用 ROOT_ORCH 建 Hub。"""
    sys.path.insert(0, C.payload('orch'))
    import orchestrator as O
    hub = O.Hub(root=C.ROOT_ORCH)
    step = max(1, n // k)
    want = set(range(1, n + 1, step))
    checked = ok = unsigned = bad = 0
    for rec in iter_records(path):
        if not rec or rec == b'\x00TAIL':
            continue
        m = re.search(rb'SEQ=(\d+) ', rec)
        if not m or int(m.group(1)) not in want:
            continue
        text = rec.decode('utf-8')
        mm = re.match(r'^\[([^\]]+)\] \[([^\]]+)\] \[([^\]]+)\] \[([^\]]+)\] '
                      r'\[id=([^\]]+)\] \[sig=([^\]]+)\] (.*)$', text, re.S)
        checked += 1
        if not mm:
            bad += 1
            continue
        e = {'time': mm.group(1), 'kind': mm.group(2), 'title': mm.group(3),
             'author': mm.group(4), 'id': mm.group(5), 'sig': mm.group(6),
             're': '', 'to': '', 'inline': mm.group(7), 'body': []}
        v = hub.entry_auth(e)
        if v == 'ok':
            ok += 1
        elif v == 'unsigned':
            unsigned += 1
        else:
            bad += 1
        if checked >= k:
            break
    return {'checked': checked, 'ok': ok, 'unsigned': unsigned, 'invalid': bad,
            'pass': bad == 0 and unsigned == 0 and checked > 0}


def selftest():
    tmp = tempfile.mkdtemp(prefix='dbb_judge_')
    agents = C.load_agents()
    n, writers = 64, 8
    write_manifest('selftest', n, writers, agents)

    def rec(seq):
        wid = C.writer_of(seq, writers)
        aid, secret = C.agent_of(wid, agents)
        return C.record(seq, wid, aid, secret).encode()

    clean = os.path.join(tmp, 'clean.txt')
    with open(clean, 'wb') as f:
        for s in range(1, n + 1):
            f.write(rec(s))

    inter = os.path.join(tmp, 'interleave.txt')
    with open(inter, 'wb') as f:
        a, b = rec(1), rec(2)
        cut = len(a) // 2
        f.write(a[:cut] + b + a[cut:])
        for s in range(3, n + 1):
            f.write(rec(s))

    miss = os.path.join(tmp, 'missing.txt')
    with open(miss, 'wb') as f:
        for s in range(1, n + 1):
            if s != 7:
                f.write(rec(s))

    dupf = os.path.join(tmp, 'dup.txt')
    with open(dupf, 'wb') as f:
        for s in range(1, n + 1):
            f.write(rec(s))
        f.write(rec(9))

    out = {}
    for name, path, want in (('clean', clean, True), ('interleave', inter, False),
                             ('missing', miss, False), ('duplicate', dupf, False)):
        r = judge_file(path, n, 'selftest')
        out[name] = {'pass': r['pass'], 'expected': want, 'ok': r['pass'] == want,
                     'failed_checks': [k for k, v in r['checks'].items() if not v['pass']]}
    out['all_ok'] = all(v['ok'] for k, v in out.items() if k != 'all_ok')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=C.VOLUME)
    ap.add_argument('--n', type=int)
    ap.add_argument('--manifest', default='main')
    ap.add_argument('--sample-verify', type=int, default=0)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--json-out', default=None)
    a = ap.parse_args(argv)
    if a.selftest:
        r = selftest()
    else:
        r = judge_file(a.file, a.n, a.manifest, a.sample_verify)
    s = json.dumps(r, ensure_ascii=False, indent=2)
    print(s)
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            f.write(s + '\n')
    return 0 if r.get('pass') or a.selftest else 1


if __name__ == '__main__':
    sys.exit(main())
