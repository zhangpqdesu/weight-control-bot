# WeChat Diet Tracker

本项目是一个给两个人使用的减肥饮食记录机器人 MVP：

- 支持文字描述和图片输入
- 调用多模态模型估算热量、蛋白质、碳水、脂肪和可信度
- 写入本地 SQLite 数据库，避免把历史记录全塞进模型上下文
- 可在 Windows PC 微信上通过 `wxauto` 监听群聊，做到“尽量不要后端”
- 可选：后续同步到飞书多维表格

## 推荐架构

第一阶段推荐：

```text
微信群聊
  -> Windows 本机微信机器人(wxauto)
  -> 多模态模型 API(小米 MiMo 或其他 OpenAI-compatible vision model)
  -> SQLite 本地数据库
  -> 微信群内返回本餐估算和当天剩余热量
```

这种方案不需要公网服务器，也不需要公众号/企业微信审核。代价是电脑需要开着，PC 微信需要保持登录。

第二阶段可以加飞书多维表格同步，把 SQLite 当本地缓存，飞书当可视化表格。

微信官方能力的边界比较重要：普通个人微信群没有官方“收群消息”的机器人 API。想保持普通微信群体验，当前最贴近的是本机 PC 微信自动化；想走官方轻量后端，入口通常要换成公众号、服务号、小程序或企业微信。详细对比见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

1. 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ".[dev]"
```

如果要在 Windows 本机使用 PC 微信自动化，再额外安装：

```powershell
pip install -e ".[wechat]"
```

2. 复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

3. 编辑 `.env`：

```env
LLM_API_KEY=你的多模态模型token
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct
WECHAT_GROUP_NAME=你们的微信群名
ME_USER_NAME=你的微信昵称
GF_USER_NAME=你女朋友的微信昵称
```

当前推荐先用硅基流动的 Qwen3-VL 8B 视觉模型，性价比高，适合日常饮食文字和图片记录：

```env
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct
```

如果遇到复杂餐盘、多人聚餐或识别效果不满意，可以临时切到更强的：

```env
LLM_MODEL=Qwen/Qwen3-VL-30B-A3B-Instruct
```

如果后续换小米 MiMo 或其他多模态模型，只需要改 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`。

4. 测试文字记录：

```powershell
python -m diet_tracker.cli add --user me --text "午饭：一碗米饭，番茄炒蛋，一杯无糖豆浆"
```

5. 测试图片记录：

```powershell
python -m diet_tracker.cli add --user gf --image "C:\path\to\meal.jpg" --text "晚饭"
```

6. 查看今天统计：

```powershell
python -m diet_tracker.cli today --user me
python -m diet_tracker.cli today --user gf
```

7. 启动微信机器人：

```powershell
python -m diet_tracker.wechat_bot
```

如果想走官方能力且不维护 HTTPS 证书，推荐优先接飞书机器人长连接：

```powershell
python -m diet_tracker.feishu_bot
```

部署步骤见 [docs/deploy-feishu.md](docs/deploy-feishu.md)。

也可以用飞书 CLI 做事件消费和消息回复：

```powershell
lark-cli event consume im.message.receive_v1 --as bot --quiet | python -m diet_tracker.feishu_cli_bridge
```

CLI 路线见 [docs/deploy-feishu-cli.md](docs/deploy-feishu-cli.md)。

服务器部署推荐 Docker：

```powershell
docker compose up -d --build
```

Docker 部署见 [docs/deploy-docker.md](docs/deploy-docker.md)。

## 群聊使用方式

在目标微信群里发：

- 文字：`午饭 一碗牛肉面 加一个茶叶蛋`
- 图片：直接发餐食图片，可补一句说明
- 群里图片：先发图片，再 `@机器人 看图`。如果机器人提示没拿到图片，需要给应用开通群消息读取权限，或改成私聊发图。
- 查看当天：`/今天`
- 绑定身份：`我是小张` / `我是小韩`
- 查看帮助：`/help`

## 自定义 Agent

可以创建 `data/agent.md` 来写长期偏好和估算规则，机器人每次估算都会读取它，不需要重建 Docker。模板见 [docs/agent.example.md](docs/agent.example.md)。

群里“先发图片，再 @机器人 看图”需要飞书权限 `获取群组中所有消息`，scope 是 `im:message.group_msg`。只开 `接收群聊中 @ 机器人消息事件` 时，机器人通常看不到未 @ 的图片消息。

机器人会按消息发送者区分你和女朋友：

- `me`: 默认建议摄入 `2600 kcal`
- `gf`: 默认建议摄入 `1600 kcal`

## 数据库

默认数据库文件：

```text
data/diet_tracker.sqlite3
```

主要表：

- `food_entries`: 每次饮食记录
- `daily_targets`: 每人的每日建议摄入

## 飞书多维表格

可以把飞书多维表格当结构化数据库使用。推荐方式是：

```text
SQLite 本地写入成功
  -> 调用飞书多维表格 API 新增记录
  -> 群里回复记录结果
```

这样微信机器人不依赖飞书实时可用，网络或 token 出问题时，本地记录也不会丢。

建议在飞书多维表格里建一张表，字段名用下面这些：

| 字段名 | 类型建议 |
| --- | --- |
| 日期 | 日期 |
| 时间 | 文本 |
| 人 | 单选/文本 |
| 餐食 | 文本 |
| 份量 | 文本 |
| 热量kcal | 数字 |
| 蛋白质g | 数字 |
| 碳水g | 数字 |
| 脂肪g | 数字 |
| 膳食纤维g | 数字 |
| 可信度 | 数字 |
| 原始输入 | 文本 |
| 图片路径 | 文本 |
| 说明 | 文本 |

开启同步需要在 `.env` 里配置：

```env
FEISHU_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BITABLE_APP_TOKEN=多维表格app_token
FEISHU_BITABLE_TABLE_ID=数据表table_id
```

飞书官方多维表格接口使用 `app_token` 和 `table_id` 定位数据表，并通过新增记录接口写入字段。参考：[新增记录 API](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create)、[多维表格概述](https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview?lang=zh-CN)。

## 注意

饮食图片热量估算天然有误差，特别是油、糖、酱料和份量。机器人返回的是“可操作估算”，不是医学诊断。减脂时建议关注 7 天趋势，而不是单餐绝对值。
