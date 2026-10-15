# daybook ORCH · 司南

**不造调度器，只做确定性查表。** 把 daybook 的 append-only 卷，变成多智能体的操作系统——  
谁该动、动到哪一步，**由表定，不由猜**。

> 名号「司南」：《韩非子·有度》「先王立司南以端朝夕」——以器定方向，**不因问者而异**：  
> 同一条，任何时刻、任何人来问，都得**同一个下一手**。

## 卖点

- **确定性** —— 编排器不贡献智能，只贡献方向：**定于查表，不定于推理**。
- **零依赖** —— 只 Python 3 标准库；不新存储、不新协议、不新依赖。
- **两张表人可读可改** —— 类 → 角色 → 人，规则写在纯文本里，**不藏在码里**。
- **不自审** —— `@非作者` 保证裁决者不是作者本人。
- **只增不改** —— 身份 / 任务 / 消息 / 心跳皆落 append-only 卷；看板、收件箱皆派生件，可删可重建。

## 十二动词 · 六原语

- **verbs（12）**：`join` `leave` `who` `open` `claim` `submit` `review` `pull` `board` `alarm` `digest` `selftest`
- **原语（6）**：身份 `agent_registry` · 任务 `task_volume` · 锁 `agent_lock` · 在场 `agent_heartbeat` · 消息 `agent_message` · 引用 `cross_ref`（＋ 路由 `orchestrator`）

## 分发接上目录（v3.1）

账本侧生成**部(卷)→类→属(条目)** 多级目录后，分发不再只是「有新条」，而是「**有新条，且已挂进层级、带提要**」：

```bash
python3 orchestrator.py digest --vol 协作 --limit 5      # 变动摘要（部▸类▸属 ＋ 互见引用）
python3 orchestrator.py digest --cls 核 --push 皮特      # 按类过滤·经 agent_message 推送
```

摘要每条附**互见引用** `↪[卷#L行-SHA8]`（可校验）。缺多级目录件时**按在册卷原文兜底**（自持可跑）；`--push` 收件人不在线**不阻断**（摘要落编排卷）。

## 怎么跑

```bash
cd daybook-orch
python3 orchestrator.py selftest      # 端到端自检（含 digest 2 项）
python3 orchestrator.py join 汤姆
python3 orchestrator.py open "实现 X" --by 汤姆
python3 orchestrator.py pull 皮特      # 取件（查表算下一手）
python3 orchestrator.py board         # 看板
```

`--root DIR` 指定卷根；`--rule / --roles` 换路由表 / 角色表。

## 边界（诚实）

- 路由**只对已知类**确定；未命中落「广播」，**不猜**。
- `flock` 是**进程级**互斥；跨主机须靠共享文件系统或上层协调。
- 与消息 socket 推送是**可接**关系，未强绑。

## 许可

**AGPL-3.0-or-later**，或另购**商业许可**。  
三件套可自由使用与修改（**含商用内部使用**）；若须**闭源嵌入 / 对外 SaaS 而不开源 / 官方支持与合规背书**——另谈商业许可。

## 作者

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>
