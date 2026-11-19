#!/bin/sh
# Daybook Setup 4.0.7 — 双击即安装（运行副本 + 密钥 + 代理 + 三方配置）。
set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$DIR/daybook-setup" install
printf '\n按回车关闭窗口...'
read -r _
