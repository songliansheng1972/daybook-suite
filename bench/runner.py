#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""压测总控：自证 → 分档并发写 → 判据 → 性能读数 → results.md。
Orchestrator: self-check → staged concurrent writes → judge → perf → results.md.

每档结束立即落盘 logs/stage_<名>.json 与 results.md；任何一档红即停，保留现场。
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

import common as C
import judge as J

BENCH = os.path.dirname(os.path.abspath(__file__))
DATA = C.DATA_ROOT
LOGS = os.path.join(DATA, 'logs')
RESULTS_MD = os.path.join(DATA, 'results.md')

STAGES = {
    'selfcheck': {'n': 10000, 'writers': 8, 'perf': False},
    '100k': {'n': 100000, 'writers': 64, 'perf': True},
    '1m': {'n': 1000000, 'writers': 256, 'perf': True},
    '1000': {'n': 200000, 'writers': 1000, 'perf': True},
}


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:   # noqa: BLE001
        return ''


def machine_info():
    mem = sh(['sysctl', '-n', 'hw.memsize'])
    try:
        mem_gb = round(int(mem) / 1073741824.0, 1)
    except ValueError:
        mem_gb = None
    dev = sh(['df', '-P', DATA]).splitlines()
    dev = dev[-1].split()[0] if dev else '/'
    du = sh(['diskutil', 'info', dev]) or sh(['diskutil', 'info', '/'])
    info = {}
    for line in du.splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            info[k.strip()] = v.strip()
    return {
        'hostname': platform.node(),
        'machine_model': sh(['sysctl', '-n', 'hw.model']),
        'cpu': sh(['sysctl', '-n', 'machdep.cpu.brand_string']),
        'cpu_cores': sh(['sysctl', '-n', 'hw.ncpu']),
        'memory_bytes': int(mem) if mem.isdigit() else None,
        'memory_gb': mem_gb,
        'os': platform.platform(),
        'python': sys.version.split()[0],
        'disk_device': dev,
        'disk_media': info.get('Device / Media Name', '') or info.get('Volume Name', ''),
        'disk_protocol': info.get('Protocol', ''),
        'disk_solid_state': info.get('Solid State', '') or info.get('Media Type', ''),
        'disk_filesystem': info.get('File System Personality', ''),
        'data_fs_type': info.get('File System Personality', ''),
        'loadavg': list(os.getloadavg()),
        'uptime': sh(['uptime']),
        'pipe_buf': os.pathconf(C.VOL_DIR, 'PC_PIPE_BUF') if os.path.isdir(C.VOL_DIR) else None,
        'exclusive': '否（未停止任何其他进程；负载见 loadavg）',
    }


# ── 子进程封装：每次调用都留原始日志 ──────────────────────────────
def run_cmd(args, name, env=None, timeout=7200):
    e = dict(os.environ)
    e['DBB_DATA'] = DATA
    e['PYTHONPATH'] = BENCH
    if env:
        e.update(env)
    t0 = time.perf_counter()
    p = subprocess.run(args, cwd=BENCH, env=e, capture_output=True, text=True, timeout=timeout)
    wall = round(time.perf_counter() - t0, 3)
    with open(os.path.join(LOGS, name + '.log'), 'w', encoding='utf-8') as f:
        f.write('CMD: %s\nWALL_S: %s\nRC: %d\n--- STDOUT ---\n%s\n--- STDERR ---\n%s\n'
                % (' '.join(args), wall, p.returncode, p.stdout, p.stderr))
    payload = None
    txt = p.stdout.strip()
    if txt:
        try:
            payload = json.loads(txt)
        except json.JSONDecodeError:
            for line in reversed([x for x in txt.splitlines() if x.strip()]):
                if line.lstrip().startswith(('{', '[')):
                    try:
                        payload = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        pass
    return {'rc': p.returncode, 'wall_s': wall, 'json': payload,
            'stdout_tail': p.stdout[-2000:], 'stderr_tail': p.stderr[-2000:]}


def py(script, args, name, env=None, timeout=7200):
    return run_cmd([sys.executable, os.path.join(BENCH, script)] + args, name, env, timeout)


# ── 准备 ──────────────────────────────────────────────────────────
def prepare(max_writers):
    C.ensure_dirs()
    os.makedirs(LOGS, exist_ok=True)
    C.write_confs()
    if not os.path.exists(C.VOLUME):
        open(C.VOLUME, 'w', encoding='utf-8').close()
    if os.path.exists(C.AGENTS_JSON):
        agents = C.load_agents()
        have = len(agents)
    else:
        agents, have = {}, 0
    if have < max_writers:
        sys.path.insert(0, C.payload('orch'))
        import orchestrator as O
        hub = O.Hub(root=C.ROOT_ORCH)
        for wid in range(have, max_writers):
            aid, secret = hub.reg.register('bench-w%d' % wid)
            agents[str(wid)] = {'aid': aid, 'secret': secret}
        os.makedirs(os.path.dirname(C.AGENTS_JSON), exist_ok=True)
        with open(C.AGENTS_JSON, 'w', encoding='utf-8') as f:
            json.dump(agents, f, ensure_ascii=False, indent=1)
        os.chmod(C.AGENTS_JSON, 0o600)
    return agents


def reset_scene():
    open(C.VOLUME, 'w', encoding='utf-8').close()
    for d in (C.MANIFEST_DIR,):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    for name in os.listdir(C.ROOT_DB):
        p = os.path.join(C.ROOT_DB, name)
        if (name.startswith('index_') or name.startswith('.cursor_')
                or name in ('.head_stamp.json', 'volumes.md') or name == '.index.lock'):
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
    shutil.rmtree(os.path.join(C.ROOT_DB, 'multilevel'), ignore_errors=True)


# ── 单档 ──────────────────────────────────────────────────────────
def stage_write(name, spec):
    r = py('writer.py', ['--n', str(spec['n']), '--writers', str(spec['writers'])],
           'writer_%s' % name)
    if r['rc'] != 0 or not r['json']:
        raise SystemExit('写卷失败（档 %s），日志见 %s' % (name, os.path.join(LOGS, 'writer_%s.log' % name)))
    return r['json']


def stage_judge(name, n, manifest, sample=0):
    args = ['--file', C.VOLUME, '--n', str(n), '--manifest', manifest,
            '--json-out', os.path.join(LOGS, 'judge_%s.json' % name)]
    if sample:
        args += ['--sample-verify', str(sample)]
    r = py('judge.py', args, 'judge_%s' % name, timeout=7200)
    if not r['json']:
        raise SystemExit('判据未产出 JSON，日志见 logs/judge_%s.log' % name)
    return r['json']


def perf_block(name, n, do_append=False):
    out = []
    ops = [('index', 'index_full'), ('index', 'index_unchanged'),
           ('query_count', 'query_count'), ('query_one', 'query_one'),
           ('multidx', 'multidx'), ('digest', 'digest')]
    # 未变复跑：同一操作跑两次，第二次即「未变」
    for i, (op, tag) in enumerate(ops):
        args = [op] + (['--needle', str(n // 2)] if op == 'query_one' else [])
        r = py('perf.py', args, 'perf_%s_%s' % (name, tag), timeout=7200)
        if not r['json']:
            raise SystemExit('perf %s 失败，日志见 logs/perf_%s_%s.log' % (tag, name, tag))
        d = dict(r['json'])
        d['tag'] = tag
        d['cli_wall_s'] = None
        out.append(d)
    # CLI 入口交叉核对（同操作再跑一次，记录墙钟）
    cli_env = {'DAYBOOK_HOME': C.ROOT_DB}
    cli = run_cmd([sys.executable, '-m', 'daybook_suite.cli', 'index'], 'cli_%s_index' % name, cli_env)
    out[1]['cli_wall_s'] = cli['wall_s']
    cli = run_cmd([sys.executable, '-m', 'daybook_suite.cli', 'query',
                   'category=' + C.KIND, '--count'], 'cli_%s_query' % name, cli_env)
    out[2]['cli_wall_s'] = cli['wall_s']
    cli = run_cmd([sys.executable, '-m', 'daybook_orch.cli', '--root', C.ROOT_DB,
                   'digest', '--limit', '20'], 'cli_%s_digest' % name,
                  {'DAYBOOK_HOME': C.ROOT_ORCH})
    out[5]['cli_wall_s'] = cli['wall_s']

    if do_append:
        k = 10000
        agents = C.load_agents()
        r = py('writer.py', ['--n', str(k), '--writers', '1', '--start', str(n + 1)],
               'writer_%s_append' % name)
        if r['rc'] != 0:
            raise SystemExit('纯追加失败，日志见 logs/writer_%s_append.log' % name)
        J.write_manifest(name, k, 1, agents, start=n + 1, append=True)
        r = py('perf.py', ['index'], 'perf_%s_index_append' % name)
        if not r['json']:
            raise SystemExit('纯追加后建索引失败')
        d = dict(r['json'])
        d['tag'] = 'index_after_append_%d' % k
        out.append(d)
        j = stage_judge(name + '_after_append', n + k, name, 200)
        return out, j
    return out, None


# ── 渲染 ──────────────────────────────────────────────────────────
def mb(v):
    return round((v or 0) / 1048576.0, 1)


def render(machine, stages, order, degraded):
    L = []
    L.append('# daybook 4.0.3 · 并发与容量压测读数\n')
    L.append('> 本文件由 `run.sh` 自动生成；所有数字来自实际运行，未执行的档明确标注「未执行」。\n')
    L.append('## 机器与口径\n')
    L.append('| 项 | 值 |\n|---|---|')
    L.append('| 主机 | %s |' % machine.get('hostname', ''))
    L.append('| 型号 | %s |' % machine.get('machine_model', ''))
    L.append('| CPU | %s（%s 核）|' % (machine.get('cpu', ''), machine.get('cpu_cores', '')))
    L.append('| 内存 | %s GB |' % machine.get('memory_gb', ''))
    L.append('| 盘 | %s / %s / %s / SSD=%s |' % (
        machine.get('disk_media', ''), machine.get('disk_protocol', ''),
        machine.get('disk_filesystem', ''), machine.get('disk_solid_state', '')))
    L.append('| 数据所在 FS | %s |' % machine.get('data_fs_type', ''))
    L.append('| OS / Python | %s / %s |' % (machine.get('os', ''), machine.get('python', '')))
    L.append('| PIPE_BUF（原子写阈值）| %s 字节 |' % machine.get('pipe_buf', ''))
    L.append('| 是否独占 | %s |' % machine.get('exclusive', ''))
    L.append('| 起始负载 | %s |' % ', '.join('%.2f' % x for x in machine.get('loadavg', [])))
    L.append('| 数据目录 | `%s` |' % DATA)
    L.append('')
    L.append('**判据四项**：总条数等于预期（`count`）／逐条 sha256 与写入清单一致（`sha`）／'
             '条目完整不跨行无交错（`inter`）／无缺号无重号（`seq`）。\n')
    L.append('## 判据自证\n')
    sc = stages.get('selfcheck')
    if sc:
        L.append('| 步骤 | 结果 | 说明 |\n|---|---|---|')
        L.append('| 注入人为交错 | %s | %s |' % (
            '红（预期）' if not sc['inject']['pass'] else '绿（**判据失效**）',
            '、'.join(k for k, v in sc['inject']['checks'].items() if not v['pass'])))
        L.append('| 注入后正常写 | %s | %s |' % (
            '绿（预期）' if sc['judge']['pass'] else '红（异常）',
            '全部四项通过' if sc['judge']['pass'] else '见 logs/judge_selfcheck.json'))
        L.append('')
    else:
        L.append('未执行。\n')
    L.append('## 分档读数\n')
    L.append('| 档位 | 条数 | 并发 | 耗时 s | 条/秒 | count | sha | inter | seq | '
             '卷 MB | 峰值内存 MB | 降档 |\n|---|---|---|---|---|---|---|---|---|---|---|---|')
    for name in order:
        s = stages.get(name)
        if not s or s.get('status') != 'done':
            L.append('| %s | — | — | — | — | — | — | — | — | — | — | 未执行 |' % name)
            continue
        w = s['write']
        j = s['judge']
        ch = j['checks']
        L.append('| %s | %d | %d | %.3f | %.1f | %s | %s | %s | %s | %.1f | %.1f | %s |' % (
            name, w['n'], w['writers'], w['wall_s'], w['entries_per_s'],
            '绿' if ch['count_equals_expected']['pass'] else '红',
            '绿' if ch['sha256_multiset_equal']['pass'] else '红',
            '绿' if ch['no_interleave']['pass'] else '红',
            '绿' if ch['no_missing_or_dup_seq']['pass'] else '红',
            mb(w['volume_bytes']), w.get('peak_rss_mb') or 0,
            s.get('degraded') or '—'))
    L.append('')
    L.append('## 性能读数（同一卷上实测）\n')
    L.append('| 档位 | 操作 | 耗时 s | CLI 墙钟 s | 读·卷 | 读·索引 | 读·多级 | 写 | '
             'ru_inblock(512B) | 峰值 RSS MB |\n|---|---|---|---|---|---|---|---|---|---|')
    for name in order:
        s = stages.get(name)
        if not s or s.get('status') != 'done':
            continue
        for p in s.get('perf', []):
            rd = p.get('read_bytes', {})
            L.append('| %s | %s | %.3f | %s | %.1f MB | %.1f MB | %.1f MB | %.1f MB | %s | %s |' % (
                name, p.get('tag', p.get('op', '')), p.get('seconds', 0),
                ('%.3f' % p['cli_wall_s']) if p.get('cli_wall_s') is not None else '—',
                mb(rd.get('volume')), mb(rd.get('index')), mb(rd.get('multilevel')),
                mb(sum(p.get('write_bytes', {}).values())),
                p.get('ru_inblock_512B', 0), p.get('maxrss_mb', '')))
    L.append('')
    L.append('## 降档与失败记录\n')
    if degraded:
        for d in degraded:
            L.append('- %s' % d)
    else:
        L.append('- 无。')
    L.append('')
    L.append('## 现场与清理\n')
    L.append('- 原始日志：`%s`' % LOGS)
    L.append('- 卷：`%s`；索引/多级目录：`%s`' % (C.VOLUME, C.ROOT_DB))
    L.append('- 默认保留现场；删除请执行 `run.sh --clean --data-dir %s`（或重跑时加 `--clean`）。' % DATA)
    L.append('')
    return '\n'.join(L) + '\n'


def write_stage(stage):
    with open(os.path.join(LOGS, 'stage_%s.json' % stage['name']), 'w', encoding='utf-8') as f:
        json.dump(stage, f, ensure_ascii=False, indent=2)


# ── 主流程 ────────────────────────────────────────────────────────
def main():
    global DATA, LOGS, RESULTS_MD
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--clean', action='store_true')
    ap.add_argument('--data-dir', default='')
    ap.add_argument('--skip-perf', action='store_true')
    a = ap.parse_args()

    if a.data_dir:
        os.environ['DBB_DATA'] = os.path.abspath(a.data_dir)
        C.DATA_ROOT = os.environ['DBB_DATA']
        C.VOL_DIR = os.path.join(C.DATA_ROOT, 'vol')
        C.VOLUME = os.path.join(C.VOL_DIR, '压测卷.txt')
        C.ROOT_ORCH = os.path.join(C.DATA_ROOT, 'run', 'orch')
        C.ROOT_DB = os.path.join(C.DATA_ROOT, 'run', 'db')
        C.MANIFEST_DIR = os.path.join(C.DATA_ROOT, 'manifest')
        C.STATE_DIR = os.path.join(C.DATA_ROOT, 'state')
        C.AGENTS_JSON = os.path.join(C.STATE_DIR, 'agents.json')
        DATA = C.DATA_ROOT
        LOGS = os.path.join(C.DATA_ROOT, 'logs')
        RESULTS_MD = os.path.join(C.DATA_ROOT, 'results.md')

    if a.quick:
        plan = ['selfcheck', '100k']
    elif a.only:
        plan = [x.strip() for x in a.only.split(',') if x.strip()]
    else:
        plan = ['selfcheck', '100k', '1m', '1000']
    for p in plan:
        if p not in STAGES:
            raise SystemExit('未知档位：%s（可选 %s）' % (p, ','.join(STAGES)))
    # 判据自证是上规模的前置：任何非自证档都先跑自证（廉价，约 1 秒）
    if 'selfcheck' not in plan:
        plan = ['selfcheck'] + plan

    max_writers = max(STAGES[p]['writers'] for p in plan)
    import resource
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    if max_writers + 64 > soft:
        raise SystemExit('ulimit -n=%d 不够（本档需 ≥%d）。请先执行：ulimit -n 8192' % (soft, max_writers + 64))

    prepare(max_writers)
    DATA = C.DATA_ROOT
    LOGS = os.path.join(C.DATA_ROOT, 'logs')
    RESULTS_MD = os.path.join(C.DATA_ROOT, 'results.md')
    os.makedirs(LOGS, exist_ok=True)
    machine = machine_info()
    with open(os.path.join(LOGS, 'machine.json'), 'w', encoding='utf-8') as f:
        json.dump(machine, f, ensure_ascii=False, indent=2)

    order = ['selfcheck', '100k', '1m', '1000']
    stages, degraded = {}, []

    # —— 自证：注入必须红，正常必须绿 ——
    if 'selfcheck' in plan:
        reset_scene()
        agents = C.load_agents()
        J.write_manifest('selfcheck', STAGES['selfcheck']['n'], STAGES['selfcheck']['writers'], agents)
        inj = py('writer.py', ['--n', str(STAGES['selfcheck']['n']),
                               '--writers', str(STAGES['selfcheck']['writers']), '--inject'],
                 'writer_selfcheck_inject')
        if inj['rc'] != 0:
            raise SystemExit('注入写卷失败，现场保留：%s' % LOGS)
        jr = stage_judge('selfcheck_inject', STAGES['selfcheck']['n'], 'selfcheck')
        if jr['pass']:
            print('\n★ 判据失效：注入人为交错后仍然全绿，本次读数作废。')
            print('  现场：%s' % LOGS)
            raise SystemExit(9)
        reset_scene()
        J.write_manifest('selfcheck', STAGES['selfcheck']['n'], STAGES['selfcheck']['writers'], agents)
        w = stage_write('selfcheck', STAGES['selfcheck'])
        j = stage_judge('selfcheck', STAGES['selfcheck']['n'], 'selfcheck', 200)
        st = {'name': 'selfcheck', 'status': 'done', 'write': w, 'judge': j,
              'inject': jr, 'perf': [], 'degraded': ''}
        stages['selfcheck'] = st
        write_stage(st)
        with open(RESULTS_MD, 'w', encoding='utf-8') as f:
            f.write(render(machine, stages, order, degraded))
        if not j['pass']:
            print('\n★ 自证档正常写未通过，停止。现场：%s' % LOGS)
            raise SystemExit(10)
        print('自证：注入判红 ✓，正常判绿 ✓')

    # —— 其余档 ——
    for name in plan:
        if name == 'selfcheck':
            continue
        spec = dict(STAGES[name])
        n, writers = spec['n'], spec['writers']
        degraded_reason = ''
        if name == '1m':
            free = shutil.disk_usage(C.DATA_ROOT).free
            mem = machine.get('memory_bytes') or 0
            if free < 3 * 1024**3:
                n = 500000
                degraded_reason = '磁盘剩余 %.2f GB < 3 GB，降为 50 万条' % (free / 1024**3)
            elif mem and mem < 6 * 1024**3:
                n = 500000
                degraded_reason = '内存 %.1f GB < 6 GB，降为 50 万条' % (mem / 1024**3)
            if degraded_reason:
                degraded.append('%s：%s' % (name, degraded_reason))
        reset_scene()
        agents = C.load_agents()
        J.write_manifest(name, n, writers, agents)
        w = stage_write(name, {'n': n, 'writers': writers})
        j = stage_judge(name, n, name, 200 if name == '1000' else 1000)
        st = {'name': name, 'status': 'done', 'write': w, 'judge': j, 'perf': [],
              'degraded': degraded_reason}
        write_stage(st)
        if not j['pass']:
            with open(RESULTS_MD, 'w', encoding='utf-8') as f:
                f.write(render(machine, stages, order, degraded))
            print('\n★ 档 %s 判据红，停止；现场保留：%s' % (name, LOGS))
            raise SystemExit(11)
        if spec['perf'] and not a.skip_perf:
            perf, aj = perf_block(name, n, do_append=(name == '1m'))
            st['perf'] = perf
            if aj is not None:
                st['judge_after_append'] = aj
                if not aj['pass']:
                    write_stage(st)
                    with open(RESULTS_MD, 'w', encoding='utf-8') as f:
                        f.write(render(machine, stages, order, degraded))
                    print('\n★ 纯追加后复判为红，停止；现场保留：%s' % LOGS)
                    raise SystemExit(12)
            write_stage(st)
        stages[name] = st
        with open(RESULTS_MD, 'w', encoding='utf-8') as f:
            f.write(render(machine, stages, order, degraded))
        print('档 %s 完成：%d 条 / %d 并发 / %.1fs / %.1f 条每秒 / 判据%s'
              % (name, w['n'], w['writers'], w['wall_s'], w['entries_per_s'],
                 '绿' if j['pass'] else '红'))

    with open(RESULTS_MD, 'w', encoding='utf-8') as f:
        f.write(render(machine, stages, order, degraded))
    print('\n读数：%s' % RESULTS_MD)

    if a.clean:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        # 归档到仓外（$HOME 下），避免 --clean 把结果留在工作树里弄脏 git
        keep = os.path.join(os.path.expanduser('~'), 'daybook-bench-results', stamp)
        os.makedirs(keep, exist_ok=True)
        shutil.copyfile(RESULTS_MD, os.path.join(keep, 'results.md'))
        shutil.copytree(LOGS, os.path.join(keep, 'logs'), dirs_exist_ok=True)
        print('读数已留档：%s' % keep)
        print('按 --clean 删除临时数据：%s' % C.DATA_ROOT)
        shutil.rmtree(C.DATA_ROOT, ignore_errors=True)
    else:
        print('现场保留：%s' % C.DATA_ROOT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
