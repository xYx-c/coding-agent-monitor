# Coding Agent Monitor（编码代理监控器）

[English README](README.md) · 一个独立运行的 **Claude Code / Codex** 本地 supervisor，并提供可选的 [Hermes Agent](https://hermes-agent.nousresearch.com/docs) Dashboard 插件。

它让编码代理具备可观察、可停止、可回放的运行面，同时**不修改 Hermes 核心源码，也不共享你日常使用的 tmux server**。

> **当前定位：**可实际使用的本地运维工具。已具备 Claude/Codex 真正的 CLI adapter、独立 tmux socket、profile 隔离、loopback API、只读 Dashboard 输出和明确停止确认。它不是交互式终端的替代品，也不是远程多用户调度服务。

## 提供的能力

- 所有 agent run 均通过 `tmux -L hermes-coding` 启动；不会使用裸 `tmux`，不会进入你的默认 tmux server。
- 只允许在已有、HEAD 可解析的 Git worktree 中启动；会记录启动时的分支和 HEAD。
- Claude Code 使用结构化 `stream-json`；Codex 使用结构化 `--json`。
- 按 Hermes profile 保存运行状态、有限事件尾部与只读 ANSI 快照。
- 仅提供带 token 的本机 loopback API；Dashboard adapter 在服务端持有 token，浏览器 JavaScript 不会得到它。
- Dashboard 的 **Coding Agents** 页面可启动、查看、刷新、展开只读输出，并精确停止某一个已知 run。
- 安装后，完整源码仓库位于用户级 Hermes 插件目录，不再依赖 `/root/coding-agent-monitor` 这个容易被误删的位置。

## 安全边界

| 边界 | 实际行为 |
| --- | --- |
| Hermes 核心 | **不会**修改 `/usr/local/lib/hermes-agent`、Dashboard bundle、原生 TUI 或 Hermes 配置。 |
| tmux | monitor 的每个 tmux 调用都明确带 `-L hermes-coding`；没有裸 `tmux`、`kill-server`、`pkill tmux`、attach 或默认 server 清理动作。 |
| 停止 | stop 只能对自动生成的 `cam-<run-id>` 发起，且必须匹配随机 ownership marker。CLI 必须带 `--yes`；API/Dashboard 必须带 `confirm: true`。 |
| 网络 | supervisor 仅允许监听 `127.0.0.1`、`::1` 或 `localhost`，不是 LAN 服务。 |
| Agent 权限 | Claude 固定使用 `--permission-mode acceptEdits`；Codex 固定使用 `--sandbox workspace-write`；不会加全局危险 bypass。 |
| Profile | list/show/output/refresh/stop 都严格检查 run 所属的 Hermes profile。 |
| 任务与记录 | CLI 任务来自 stdin 或普通 task file，不进入进程参数。原始任务不会被有意写入 run manifest 或 API metadata。 |
| 敏感信息 | transcript、事件和 API 返回会在落盘/返回前脱敏。这只是纵深防御；不要把凭据写进任务或命令。 |

## 前置条件

- Linux，且具备用户级 systemd session（`systemctl --user`）
- 带 Dashboard 插件能力的 Hermes Agent
- `uv`、`git`、`tmux`
- 已安装并可在 service `PATH` 中找到 Claude Code（`claude`）和/或 Codex（`codex`）
- 你明确允许对应 agent 编辑的 Git worktree

独立 supervisor 自身没有第三方 Python 依赖；Dashboard adapter 使用 Hermes 已自带的 Python 依赖。

## 安装

可以先临时 clone 到任意位置。安装器会把一份干净的源码副本复制到目标 profile 的插件目录；成功后 `/root/coding-agent-monitor` 不再是运行时源码。

```bash
git clone https://github.com/xYx-c/coding-agent-monitor.git /tmp/coding-agent-monitor
cd /tmp/coding-agent-monitor
./install.sh coder
```

安装器会完成以下动作：

1. 将完整项目复制到：
   ```text
   <profile-home>/plugins/coding-agent-monitor/source
   ```
2. 将轻量 Dashboard adapter 复制到：
   ```text
   <profile-home>/plugins/coding-agent-monitor/dashboard
   ```
3. 安装 `~/.local/bin/coding-agent-monitor` wrapper，该 wrapper 使用 profile 本地源码通过 `uv` 运行；
4. 创建并启用用户级 `coding-agent-monitor-<profile>.service`；
5. 启用该用户级 Hermes 插件。

profile home 由 `hermes --profile <名称> config path` 推导。`coder` 通常对应 `~/.hermes/profiles/coder`。

安装完需要重启当前 Dashboard 进程，再打开或刷新 **Coding Agents**（`/coding-agents`）页面：

```bash
hermes --profile coder dashboard
```

### 升级

在较新的源码 checkout 中再次执行安装器即可。它会先准备一份干净的源码副本，再替换安装后的源码、重启用户服务并重新复制 Dashboard adapter，**不会删除历史 run**。

```bash
cd /path/to/new/coding-agent-monitor
./install.sh coder
```

### 服务管理

```bash
systemctl --user status coding-agent-monitor-coder.service
systemctl --user restart coding-agent-monitor-coder.service
journalctl --user -u coding-agent-monitor-coder.service -f
```

每个 profile 的 endpoint 与 token 位于：

```text
<profile-home>/coding-agent-monitor/profiles/<profile>/
```

这些是私有本地实现细节。不要把 token 放进浏览器、shell history、仓库或 issue。

## 日常 CLI 使用

安装后使用 `coding-agent-monitor`：

```bash
# Claude：stdin 避免任务文本出现在进程参数中。
printf '%s\n' '检查失败的测试，并进行最小且安全的修复。' \
  | coding-agent-monitor start \
      --agent claude \
      --workdir /绝对路径/可信任/git-worktree \
      --task-stdin \
      --profile coder

# Codex：
printf '%s\n' '实现所需改动，并运行有针对性的测试。' \
  | coding-agent-monitor start \
      --agent codex \
      --workdir /绝对路径/可信任/git-worktree \
      --task-stdin \
      --profile coder

# 或使用你自己拥有、可读的普通任务文件：
coding-agent-monitor start \
  --agent claude \
  --workdir /绝对路径/可信任/git-worktree \
  --task-file /安全路径/task.txt \
  --profile coder
```

随后查看或停止某一个 run：

```bash
coding-agent-monitor list --profile coder
coding-agent-monitor show <run-id> --profile coder
coding-agent-monitor refresh <run-id> --profile coder
coding-agent-monitor stop <run-id> --profile coder --yes
```

`start` 会拒绝：非 Git 目录、无法解析 HEAD 的目录、未知 agent、找不到的可执行文件、空任务和不安全的 task-file 类型。它不会替你清理 dirty worktree，也不会判断 agent 的改动是否应提交；这些仍然由操作者负责。

## Dashboard 使用方式

1. 在**同一个 profile**启动 Hermes Dashboard，进入 **Coding Agents** 页面。
2. 选择 Claude Code 或 Codex。
3. 填写可信任 Git worktree 的绝对路径和任务。
4. 点击 **Start isolated run**。
5. 用刷新或展开操作查看状态、元数据、事件和**只读**终端输出。
6. 仅在确定需要时，通过单 run 的停止操作并完成确认。

关闭 Dashboard 只会停止观察，不会停止 agent。页面没有终端键盘注入能力，这是有意为之。

## 落盘目录与数据

每个 profile 的运行资料在插件源码目录之外：

```text
<profile-home>/coding-agent-monitor/
├── profiles/<profile>/
│   ├── api.token        # 0600；不可泄露
│   └── endpoint.json    # 仅 local loopback 地址
└── runs/<run-id>/
    ├── manifest.json    # agent/worktree/branch/HEAD，仅任务摘要
    ├── status.json
    ├── events.jsonl     # 脱敏事件尾部/历史
    ├── terminal.ansi    # 脱敏的只读终端快照
    ├── ownership.token  # 0600 的 ownership guard
    └── launch.sh        # 临时 task-file 路径；没有任务正文
```

任务文件会使用 `0600` 创建，优先在 `/dev/shm`；它经 stdin 传给 agent，并在 agent 退出后由 launch script 删除。脱敏只是额外安全层，不代表可以输入敏感信息。

## 卸载

从安装后的本地源码执行：

```bash
~/.hermes/profiles/coder/plugins/coding-agent-monitor/source/uninstall.sh coder
```

卸载只会禁用/删除本 monitor 的用户服务、wrapper、Dashboard adapter 和安装后的源码；它会**保留** profile home 下的 `coding-agent-monitor/runs`，由你在审核后自行决定是否删除。

卸载过程不会 list、attach、修改或停止默认 tmux session。

## 开发与验证

```bash
cd /path/to/coding-agent-monitor
bash -n install.sh uninstall.sh
uv run python -m compileall -q coding_agent_monitor dashboard_plugin/dashboard/plugin_api.py
uv run python -m unittest discover -s tests -v
```

测试涵盖：命令安全、状态转换、worktree 校验、profile 隔离、任务不持久化、脱敏、loopback API 鉴权、停止确认、插件 manifest/API proxy guard，以及证明私有 socket run 不会改变默认 tmux server 的集成测试。

Dashboard proxy 的测试需使用 Hermes runtime Python，因为 FastAPI/Pydantic 由 Hermes 提供，不属于独立 supervisor 的依赖：

```bash
cd tests
/usr/local/lib/hermes-agent/venv/bin/python run_plugin_runtime.py
```

`tests/run_plugin_runtime.py` 被有意忽略：它是环境相关的验证 helper，不是交付程序代码。

## 范围与限制

- 这不是 Hermes 原生 TUI `/agents` 集成；那会要求改 Hermes core。Dashboard plugin 是不改 core、可升级维护的集成面。
- agent 的状态仅说明进程与结构化输出观察结果，不等于其生成的代码或测试一定正确。
- ANSI 输出是可见 pane 的快照，不是完整终端审计录像。
- 项目明确不提供远程控制、LAN 监听、共享多用户队列、任意 tmux target 和交互式终端注入。

## License

目前尚未选择许可证。若要在预期的私有仓库以外分发，请先添加许可证。

## 安全问题报告

若怀疑出现 secret 泄漏、stop 越权或 tmux 隔离问题，不要将凭据贴到公开 issue。先停掉服务，只保留脱敏后的证据，再私下告知仓库所有者：

```bash
systemctl --user disable --now coding-agent-monitor-coder.service
```

该命令只停止 monitor 自己的用户级 service，不会影响你的日常 tmux server。
