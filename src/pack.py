#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack.py —— daybook-suite 三包打包器（W-77·皮特 2026-10-08）
================================================================
把 daybook 3/ 源码打成三个自包含、可整拷即跑的发布包：
  daybook/        起居注（账＋录·基座）
  daybook-mcp/    璇玑（查·MCP 服务器）
  daybook-orch/   司南（令·编排中心）

设计要义
  · 源不重复：源码只此一份（daybook 3/）。包是产物，由本脚本生成，不手维护副本。
  · 自包含：各包拷齐所需件；拷到任何机器即可跑（不依赖 daybook 3/）。
  · 版本号：各包版本号 = 该包产品 .py 件行数之和（承 daybook 旧例）。
  · 源名兼容：conf/doc 优先取新英文名，找不到回退旧中文名（兼容 S3 改名前后）。
  · 不叉：三包各含一份核心件产物（daybook_append.py / safeio.py）；改先落回源，再重打包。
  · 许可分层（W-DB-025）：许可按「件」切，不按「包」切——daybook/mcp 两包 LICENSE 走源
    LICENSE（MIT）；orch 包 LICENSE 走源 LICENSE.orch（AGPL-3.0-or-later）；三包各附
    LICENSING.md / volume_format_spec.md。详见源 LICENSING.md。

用法
  python3 pack.py --out ~/Desktop/daybook-suite --pkg all
  python3 pack.py --pkg daybook --out /tmp/test
  python3 pack.py --pkg mcp   --out /tmp/test
  python3 pack.py --pkg orch  --out /tmp/test --dry
退出码：0 正常；2 参数/缺件。
"""
import argparse
import glob
import hashlib
import io
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 样本卷（发布必备·供下载者即下即跑）──────────────────
# 每卷 5 条假条目·体例与生产卷一致。由 pack.py 随三包各装一份。
# 三包皆装的理由：三包都含 cross_ref.py，其 _vol_path() 会回退到 <包>/sample/ 找卷，
# 且 daybook 包发行 conf 的卷表直接指向 sample/ 三卷（判_478 甲）。
SAMPLE = ['sample/README.md',
          'sample/协作卷.txt',
          'sample/辞海卷.txt',
          'sample/大宗师卷.txt']

# ── 三包定义 ──────────────────────────────────────────────
# prog        : 计入版本号的 .py 产品件
# prog_aux    : 不计版本号的辅助件（.sh/.c/.bas/.f 语言端口、哨兵）
# conf        : 原名拷贝的配置
# conf_rename : [(候选源名列表, 目标名)] 改名拷贝（新名优先·旧名回退）
# doc         : 原名拷贝的文档
# doc_rename  : [(候选源名列表, 目标名)] 改名拷贝
# sub         : 子路径件（带目录名·原路径拷贝；build 与一致守卫同需支持子目录）
#
# 发行 conf（承 #314-C·判_478 甲/乙）
#   · daybook 包**不再直拷生产 conf**（原 'conf': ['daybook.conf'] 会把老宋本机的
#     绝对路径连私卷名一起装进发行件）；改走 daybook.dist.conf —— 与 mcp 包
#     'daybook.sample.conf' 同一手法：发行件里只装样板，不装真账。
PACKAGES = {
    'daybook': {
        'box': 'daybook',
        'prog': ['daybook.py', 'daybook_append.py', 'safeio.py',
                 'daybook_record.py', 'daybook_session_hook.py', 'daybook_hook.py'],
        'prog_aux': ['daybook.sh', 'daybook.c', 'daybook.bas', 'daybook.f',
                     'sentinel.sh', 'sentinel-daemon.sh'],
        'conf_rename': [
            # 判_478 甲/乙·旗舰包改走发行 conf（零绝对路径·卷表只挂 sample/ 三卷）
            (['daybook.dist.conf'], 'daybook.conf'),
        ],
        # README.en.md：旗舰包亦须中英双 README（与 mcp/orch 一致·#470 观察①补装）
        'doc': ['LICENSE', 'README.md', 'README.en.md', 'LICENSING.md',
                'volume_format_spec.md', 'CLA.md'],
        'sub': SAMPLE,
    },
    'mcp': {
        'box': 'daybook-mcp',
        'prog': ['mcp_server.py', 'mcp_tools.py', 'mcp_resources.py',
                 'mcp_prompts.py', 'mcp_subscribe.py', 'mcp_transport.py',
                 'daybook_append.py', 'safeio.py',
                 # 下两件为 mcp_tools 顶层 import 所需（daybook＋agent_registry）
                 # 工单 §四 S1 mcp 核心件清单缺此两件·不补则 J3 自包含/J4 可启 不成立·订正
                 'daybook.py', 'agent_registry.py',
                 # #312·mcp_tools L431/L439 函数内懒 import cross_ref·须入包·订正
                 'cross_ref.py'],
        'conf_rename': [
            # #314-C·mcp 包样板 conf·改名拷为 daybook.conf·不污染源真账 daybook.conf
            (['daybook.sample.conf'], 'daybook.conf'),
        ],
        'doc': ['LICENSE', 'LICENSING.md', 'volume_format_spec.md',
                'CLA.md'],
        'doc_rename': [
            (['README.mcp.md'], 'README.md'),
            (['README.mcp.en.md'], 'README.en.md'),
        ],
        'sub': SAMPLE,
    },
    'orch': {
        'box': 'daybook-orch',
        'prog': ['orchestrator.py', 'agent_registry.py', 'agent_lock.py',
                 'agent_heartbeat.py', 'agent_message.py', 'task_volume.py',
                 'cross_ref.py', 'daybook_append.py', 'safeio.py'],
        'conf_rename': [
            (['orchestration_routing.conf', '编排_路由表.conf'], 'orchestration_routing.conf'),
            (['orchestration_roles.conf', '编排_角色.conf'], 'orchestration_roles.conf'),
        ],
        'doc_rename': [
            (['orchestrator.md', '编排中心.md'], 'orchestrator.md'),
            (['README.orch.md'], 'README.md'),
            (['README.orch.en.md'], 'README.en.md'),
            # W-DB-025：orch 之 LICENSE 由 LICENSE.orch 拷入（AGPL-3.0）；daybook/mcp 两包 LICENSE 仍 MIT
            (['LICENSE.orch'], 'LICENSE'),
        ],
        'doc': ['LICENSING.md', 'volume_format_spec.md', 'CLA.md'],
        'sub': SAMPLE,
    },
}


def count_lines(path):
    n = 0
    with io.open(path, 'rb') as f:
        for _ in f:
            n += 1
    return n


def resolve_src(src_dir, candidates):
    """候选源名按序找，返回首个存在的路径；都无则 None。"""
    for name in candidates:
        p = os.path.join(src_dir, name)
        if os.path.exists(p):
            return p
    return None


def plan_for(spec, src):
    """按包定义算出 [(源路径, 目标名)] 与缺件清单（build_one 与 verify_one 共用）。"""
    plan = []  # [(src_path, dst_name)]
    missing = []
    flat = (spec.get('prog', []) + spec.get('prog_aux', [])
            + spec.get('conf', []) + spec.get('doc', [])
            + spec.get('sub', []))
    for f in flat:
        sp = os.path.join(src, f)
        if not os.path.exists(sp):
            missing.append(f)
        else:
            plan.append((sp, f))
    for candidates, dst_name in (spec.get('conf_rename', [])
                                 + spec.get('doc_rename', [])):
        sp = resolve_src(src, candidates)
        if sp is None:
            missing.append(candidates[0])
        else:
            plan.append((sp, dst_name))
    return plan, missing


def md5_of(path):
    h = hashlib.md5()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_one(pkg_key, spec, src, out_root):
    """逐件比对「产物 == 源」md5；返回失配清单 [(盒, 件, 因)]。"""
    box = spec['box']
    dest = os.path.join(out_root, box)
    plan, missing = plan_for(spec, src)
    bad = [(box, f, '源缺件') for f in missing]
    for sp, dn in plan:
        dp = os.path.join(dest, dn)
        if not os.path.exists(dp):
            bad.append((box, dn, '产物缺'))
        elif md5_of(sp) != md5_of(dp):
            bad.append((box, dn, '产物≠源'))
    return bad


def verify_all(targets, src, out_root):
    """一致守卫：逐包逐件比对「产物 == 源」md5；全同返 0，失配返 3。
    （承 W-DB-026 丁·防「改了产物不落源·重打包静默抹」）"""
    print('== 一致守卫：产物 == 源 校验 ==')
    bad = []
    for name in targets:
        bad += verify_one(name, PACKAGES[name], src, out_root)
    if bad:
        print('  失配 %d 件（产物已偏离源）：' % len(bad), file=sys.stderr)
        for box, dn, why in bad:
            print('    ✗ %-14s %-26s %s' % (box + '/', dn, why), file=sys.stderr)
        print('  ⇒ 源为唯一改动点：请把改动落回源，再重打包。', file=sys.stderr)
        return 3
    print('  全同 ✓（%d 包逐件比对通过）' % len(targets))
    return 0


def build_one(pkg_key, spec, src, out_root, dry=False):
    box = spec['box']
    dest = os.path.join(out_root, box)
    print('== %s （盒 %s/）==' % (pkg_key, box))
    plan, missing = plan_for(spec, src)
    if missing:
        print('  缺件：%s' % '、'.join(missing), file=sys.stderr)
        return 2

    prog_files = spec.get('prog', [])
    total = sum(count_lines(os.path.join(src, f)) for f in prog_files)
    print('  产品 .py 件 %d 个，版本号（行数和）= %d' % (len(prog_files), total))
    for f in prog_files:
        print('    %-26s %5d 行' % (f, count_lines(os.path.join(src, f))))

    if dry:
        print('  (dry·不拷贝)')
        return 0

    if os.path.exists(dest):
        shutil.rmtree(dest)   # 仅删本包目录（产物·可删，承 §八）；不动根与源
    os.makedirs(dest)
    for sp, dn in plan:
        dp = os.path.join(dest, dn)
        sub = os.path.dirname(dp)
        if sub and not os.path.isdir(sub):
            os.makedirs(sub)          # sub 类目（如 sample/）·支持子路径件
        shutil.copy2(sp, dp)
    # ── 清运行时残留件（防发布包带垃圾·承 #360 小债）──
    # daybook.py index 产生 volumes.md / 索引_*；safeio 产生 .safeio_lock.*
    # 这些是运行时产物·不应随发布包发出·每次打包都清一遍
    for pat in ('.safeio_lock.*', 'volumes.md', '索引_*', '*.pyc'):
        for pp in glob.glob(os.path.join(dest, pat)):
            try:
                os.remove(pp)
            except OSError:
                pass
    for pp in glob.glob(os.path.join(dest, '__pycache__')):
        shutil.rmtree(pp, ignore_errors=True)   # 承 #470 观察②·清缓存目录
    with io.open(os.path.join(dest, '版本.txt'), 'w', encoding='utf-8') as f:
        f.write('daybook-suite · %s\n版本号 = %d 个产品 .py 件行数之和\n生成于 %s\n'
                % (box, total, time.strftime('%Y-%m-%d %H:%M')))
    print('  已生成：%s' % dest)
    return 0


def main():
    ap = argparse.ArgumentParser(description='daybook-suite 三包打包器')
    ap.add_argument('--src', default=HERE, help='源码目录（默认脚本所在）')
    ap.add_argument('--out', default=os.path.dirname(HERE),
                    help='产出根目录（默认源目录之上一级＝suite 根）')
    ap.add_argument('--pkg', choices=['daybook', 'mcp', 'orch', 'all'], default='all',
                    help='打哪个包（默认 all）')
    ap.add_argument('--dry', action='store_true', help='只算与列清单，不拷贝')
    ap.add_argument('--verify', action='store_true',
                    help='不拷贝·只逐件比对「产物 == 源」md5（失配即非零退出）')
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    out_root = os.path.abspath(os.path.expanduser(args.out))
    targets = list(PACKAGES) if args.pkg == 'all' else [args.pkg]

    if args.verify:
        return verify_all(targets, src, out_root)

    rc = 0
    for name in targets:
        r = build_one(name, PACKAGES[name], src, out_root, dry=args.dry)
        if r:
            rc = r
    if not rc and not args.dry:
        if args.pkg == 'all':
            print('三包已生成于：%s' % out_root)
            print('自验：')
            print('  cd "%s/daybook"      && python3 daybook.py index' % out_root)
            print('  cd "%s/daybook-orch" && python3 orchestrator.py selftest' % out_root)
        vrc = verify_all(targets, src, out_root)   # 一致守卫（承 W-DB-026 丁）
        if vrc:
            rc = vrc
    return rc


if __name__ == '__main__':
    sys.exit(main())
