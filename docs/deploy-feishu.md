# 飞书官方长连接部署

这条路线适合你现在的约束：

- 不想自己维护 HTTPS 证书
- 有一台阿里云轻量服务器
- 希望尽量使用飞书官方能力
- 数据库想放在飞书多维表格

核心架构：

```text
飞书群/单聊
  -> 飞书自建应用机器人
  -> 飞书官方长连接 WebSocket
  -> 阿里云轻量服务器上的 Python 进程
  -> 硅基流动 Qwen3-VL
  -> SQLite 本地兜底
  -> 飞书多维表格同步
```

长连接模式是关键：你的服务器不需要暴露公网 HTTP 服务，也不需要 HTTPS 证书。服务器只要能主动访问公网即可。

## 1. 创建飞书自建应用

1. 打开飞书开放平台，进入开发者后台。
2. 创建“企业自建应用”。
3. 开启“机器人”能力。
4. 记录：
   - `App ID`
   - `App Secret`
   - `Verification Token`
   - `Encrypt Key`，可先留空，MVP 阶段简单些

## 2. 配置事件订阅

在应用的“事件与回调”里：

1. 订阅方式选择“使用长连接接收事件”。
2. 添加事件：`接收消息 im.message.receive_v1`。
3. 权限按提示开通，通常需要：
   - 接收机器人单聊消息
   - 接收群聊中 @ 机器人消息
   - 获取与发送单聊、群组消息
   - 获取消息中的资源文件，用于下载用户发来的图片
4. 保存后发布应用版本。

飞书官方文档说明事件订阅支持“发送至开发者服务器”和“使用长连接接收事件”两种方式；长连接模式适合不想提供公网 HTTPS 的场景。

## 3. 创建多维表格

建一张表，字段使用：

```text
日期
时间
人
餐食
份量
热量kcal
蛋白质g
碳水g
脂肪g
膳食纤维g
可信度
原始输入
图片路径
说明
```

把自建应用添加为文档应用，并给多维表格读写权限。

## 4. 配置服务器

在服务器上：

```bash
git clone <你的仓库地址>
cd <项目目录>
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`：

```env
LLM_API_KEY=你的硅基流动key
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct

FEISHU_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
FEISHU_ENCRYPT_KEY=
FEISHU_BITABLE_APP_TOKEN=xxx
FEISHU_BITABLE_TABLE_ID=xxx

FEISHU_ME_OPEN_ID=ou_xxx
FEISHU_GF_OPEN_ID=ou_xxx
```

`FEISHU_ME_OPEN_ID` 和 `FEISHU_GF_OPEN_ID` 第一次可以先不填。你们分别给机器人发一条消息，程序会提示“不认识这个飞书用户”，日志里能看到事件数据，再把 open_id 填回 `.env`。

## 5. 启动机器人

```bash
python -m diet_tracker.feishu_bot
```

飞书里使用：

```text
@机器人 午饭 一碗米饭，番茄炒蛋，一份青菜
```

或直接私聊机器人：

```text
晚饭 牛肉面一碗
```

发图片也可以，机器人会下载图片，交给视觉模型估算热量。

## 6. 用 systemd 常驻

创建 `/etc/systemd/system/diet-feishu-bot.service`：

```ini
[Unit]
Description=Diet Feishu Bot
After=network.target

[Service]
WorkingDirectory=/opt/diet-tracker
ExecStart=/opt/diet-tracker/.venv/bin/python -m diet_tracker.feishu_bot
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable diet-feishu-bot
sudo systemctl start diet-feishu-bot
sudo journalctl -u diet-feishu-bot -f
```

## 微信怎么选

如果你坚持“普通个人微信群”，官方后端路线基本走不通，因为普通微信群没有官方机器人读取群消息 API。

如果你愿意换成官方微信入口，可以考虑：

- 微信公众号：用户私聊公众号记录，需要 HTTPS 回调或微信云托管。
- 微信小程序：做一个轻量记录界面，云开发/云托管负责后端。
- 企业微信：企业微信应用/机器人更官方，但不是普通微信个人群。

以你现在的目标，飞书长连接是最省心、最合规、最少证书维护的路线。

