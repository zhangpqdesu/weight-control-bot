# 飞书 CLI 接入路线

飞书 CLI 可以用。它适合把飞书操作从 Python 代码里移出去：

- 用 `lark-cli event consume im.message.receive_v1` 接收消息事件
- 用 `lark-cli im +messages-reply` 回复消息
- 用 `lark-cli im +messages-resources-download` 下载图片
- 用 `lark-cli base +record-upsert` 写多维表格

项目里的 Python 只保留饮食业务逻辑：解析事件、调用视觉模型、写 SQLite、生成回复。

## 适不适合你

适合：

- 不想维护 HTTPS 证书
- 想尽量走飞书官方工具
- 想让 Agent/命令行直接操作飞书
- 阿里云轻量服务器可以常驻一个进程

不适合：

- 完全不想跑任何常驻进程
- 仍然要求普通个人微信群收消息

## 1. 安装飞书 CLI

```bash
npm install -g @larksuite/cli@latest
```

或临时使用：

```bash
npx @larksuite/cli@latest --help
```

## 2. 初始化飞书应用和认证

按照官方引导：

```bash
lark-cli config init
lark-cli auth login
lark-cli doctor
```

也可以让 Agent 帮你安装，官方文档：

```text
https://open.feishu.cn/document/mcp_open_tools/feishu-cli-let-ai-actually-do-your-work-in-feishu
```

注意：CLI 不能绕过飞书应用创建和权限配置。仍然需要在飞书开放平台创建自建应用、开启机器人、开通权限并发布版本。

## 3. 飞书开放平台配置

在自建应用里：

1. 开启机器人能力。
2. 事件订阅添加 `im.message.receive_v1`。
3. 开通权限：
   - 接收机器人单聊消息
   - 接收群聊中 @ 机器人消息
   - 获取与发送单聊、群组消息
   - 获取消息中的资源文件
   - 多维表格记录读写
4. 发布应用版本。

## 4. 配置项目 `.env`

```env
LLM_API_KEY=你的硅基流动key
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct

FEISHU_ENABLED=true
FEISHU_BITABLE_APP_TOKEN=xxx
FEISHU_BITABLE_TABLE_ID=xxx
FEISHU_SYNC_MODE=cli

FEISHU_ME_OPEN_ID=ou_xxx
FEISHU_GF_OPEN_ID=ou_xxx

LARK_CLI_CMD=lark-cli
```

`FEISHU_ME_OPEN_ID` 和 `FEISHU_GF_OPEN_ID` 不知道时，可以先留空。你们也可以直接在飞书里发 `我是小张` / `我是小韩` 绑定身份，机器人会写入 SQLite，不需要重启 Docker。

如果没有全局安装 CLI，也可以临时用 npx：

```env
LARK_CLI_CMD=npx @larksuite/cli@latest
```

Windows 下如果直接运行 Python bridge，也可以写成：

```env
LARK_CLI_CMD=npx.cmd @larksuite/cli@latest
```

## 5. 启动 CLI 版机器人

```bash
tail -f /dev/null | lark-cli event consume im.message.receive_v1 --as bot --quiet \
  | python -m diet_tracker.feishu_cli_bridge
```

PowerShell：

```powershell
lark-cli event consume im.message.receive_v1 --as bot --quiet --timeout 0 | python -m diet_tracker.feishu_cli_bridge
```

群聊里使用：

```text
@机器人 午饭 一碗米饭，番茄炒蛋，一份青菜
```

私聊机器人也可以直接发：

```text
晚饭 牛肉面一碗
```

## 6. systemd 常驻

创建 `/etc/systemd/system/diet-feishu-cli-bot.service`：

```ini
[Unit]
Description=Diet Feishu CLI Bot
After=network.target

[Service]
WorkingDirectory=/opt/diet-tracker
ExecStart=/bin/bash -lc 'tail -f /dev/null | lark-cli event consume im.message.receive_v1 --as bot --quiet | /opt/diet-tracker/.venv/bin/python -m diet_tracker.feishu_cli_bridge'
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable diet-feishu-cli-bot
sudo systemctl start diet-feishu-cli-bot
sudo journalctl -u diet-feishu-cli-bot -f
```

## CLI 路线和 SDK 路线怎么选

优先选 CLI 路线，如果你想让飞书操作尽量官方、透明、可调试。

保留 SDK 路线，如果你想减少对外部命令的依赖，所有逻辑都在 Python 进程里。
