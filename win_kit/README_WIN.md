# DAYBOOK · Windows 实机验证包

这个包只做一件事：在**你的 Windows 笔记本**上，把 DAYBOOK 的 Windows 写路径真跑一遍，
把屏幕输出原样贴回来。你不需要判断对错，也不需要装任何第三方库。

- 只用 Python 标准库，零依赖。
- 所有测试文件都建在系统临时目录，跑完自动删除；不碰系统设置、不写你的项目目录。
- 全程约 10 秒。

## 一、准备 Python（只做一次）

需要 **Python 3.10 或更高版本**。

1. 打开 <https://www.python.org/downloads/windows/>，下载 64-bit 的 Python 3.10+ 安装包。
2. 安装时**务必勾选**第一页最下方的 `Add python.exe to PATH`，再点 `Install Now`。
3. 装完后打开「命令提示符」（按 Win+R，输入 `cmd`，回车），输入：

   ```
   python --version
   ```

   能看到 `Python 3.10.x`（或更高）即成功。若提示找不到命令，试 `py --version`；
   两个都不行，说明 PATH 没勾上，重新运行安装包选 `Modify` → 勾选 PATH。

## 二、运行（一条命令）

1. 把 `win_kit.zip` 解压到桌面（右键 → 全部解压缩），得到 `win_kit` 文件夹。
2. 在命令提示符里进入该文件夹（把下面路径换成你的实际路径）：

   ```
   cd %USERPROFILE%\Desktop\win_kit
   ```

3. 运行：

   ```
   python win_check.py
   ```

   如果 `python` 不可用，就改用：

   ```
   py win_check.py
   ```

## 三、预期输出长什么样

正常应当看到六行 `[PASS]`，例如：

```
DAYBOOK Windows 实机验证包
根目录：C:\Users\you\AppData\Local\Temp\daybook_win_check_xxxx
[PASS] ① 命名互斥量：两进程同卷追加条数正确
       读数：进程 rc=[0, 0] 墙钟=...ms 行数=301（期望 301）可解析=301 坏行=0 ...
[PASS] ② 进程被强杀：持锁自动放弃，另一进程可取锁写入
       读数：taskkill /F rc=0 后取得锁并写入=...ms 标记在卷=True 行数=2
[PASS] ③ 越界拒绝：junction/symlink 指向根外，写入被拒且根外零文件
       读数：链接方式=mklink /J 拒绝=True 根外文件=[] 文案=...
[PASS] ④ 文件身份复核：追加期间目标被替换必须报错
       读数：真换入=...；身份注入 st_ino (..., ...)，复核报错=...在追加期间被替换...
[PASS] ⑤ 大小写不敏感：VOL.TXT 与 vol.txt 同一文件，归属判/去重不误判
       读数：... samefile=True st_ino 相同=True 行数=3 ...
[PASS] ⑥ 换行与编码：UTF-8 中文与 CRLF 混入后仍一条记录一行
       读数：末字节=0x0a 行数=3 可解析=3 坏行=0 CRLF=1 中文可解码=是 ...

环境：Python 3.x.y（64 位）· sys.platform=win32 · cwd=...
计数：PASS 6 · FAIL 0 · SKIP 0（SKIP 不计入通过）
WINDOWS 实机验证：6/6 通过
```

末尾那行 `WINDOWS 实机验证：n/6 通过` 就是结论。

## 四、如果出现 FAIL 或 SKIP

**不用你排查**：把命令提示符窗口里的**全部内容**（从 `DAYBOOK Windows 实机验证包`
到最后一行）复制、贴回来即可。FAIL 的读数行已经带了判断所需的上下文（条数、耗时、
文件路径、错误文案）；SKIP 也会打印具体原因，不会静默跳过、也不算作通过。

常见但**不影响结论**的情况：

- ⑤ 显示 `SKIP ... 当前不是 Windows`：说明你不是在 Windows 上跑的（本包就是给 Windows 用的）。
- ③ 显示 `SKIP 无法创建 junction/symlink`：公司策略禁用了 `mklink`；请把 SKIP 原文贴回即可。

## 五、六项判据在验什么

| 项 | 判据 |
| --- | --- |
| ① 命名互斥量 | 两个进程同时向同一卷各追加 150 条：最终 301 行、全部可解析、300 个写者标记无重复（无覆盖、无丢更新）。 |
| ② 进程被强杀 | 子进程持锁后被 `taskkill /F`：主进程须在 10 秒内拿到锁并写入成功（互斥量被系统自动放弃）。 |
| ③ 越界拒绝 | 根内建 `mklink /J`（失败再试 `mklink /D`）指向根外：向链接内写入必须抛错，且根外目录零文件。 |
| ④ 文件身份复核 | 追加期间目标被换掉（真换入 + `st_ino` 注入两种方式）：必须报「在追加期间被替换」，不许静默成功。 |
| ⑤ 大小写不敏感 | `VOL.TXT`、`vol.txt`、`Vol.TxT` 是同一文件（`samefile=True`、`st_ino` 相同）；三种拼写追加都落到同一文件；根路径大小写混写不误拒、不写出根外。 |
| ⑥ 换行与编码 | 卷内混有 `\r\n` 与 `\n`，追加 UTF-8 中文后：末字节为 `\n`、三条记录逐行可解析、无坏行、无连续空行。 |

## 六、口径（重要，避免误读）

**Windows 写路径已在代码中实现，但尚未在 Windows 实机验证（第 1–6 项）。**
在收到这份实机输出之前，README/发布说明不会写「已支持 Windows」；收到并通过后，
才把口径改为「已在 Windows 实机验证（6/6）」，并把本机读数补进 CHANGELOG。

本包内嵌的 `safeio.py` 与 v4.0.6 发行件同源（不是另写一份实现），所以验的是真实写路径。
