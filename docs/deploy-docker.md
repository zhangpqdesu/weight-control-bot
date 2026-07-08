# Docker 部署

这条路线适合把机器人直接丢到阿里云轻量服务器上跑。

容器里包含：

- Python 饮食分析服务
- 飞书 CLI
- 飞书事件长连接监听
- SQLite 本地兜底数据库

服务器只需要 Docker / Docker Compose 和一个 `.env` 文件。

## 1. 准备 `.env`

在项目根目录创建 `.env`：

```env
LLM_API_KEY=你的硅基流动key
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct

FEISHU_APP_ID=cli_aac1317404b85cda
FEISHU_APP_SECRET=你的飞书AppSecret
FEISHU_BRAND=feishu

FEISHU_ME_OPEN_ID=ou_b4671b9f4ce893036b46c4e145e29dd1
FEISHU_GF_OPEN_ID=你女朋友的open_id

ME_DAILY_TARGET_KCAL=2600
GF_DAILY_TARGET_KCAL=1600

DATABASE_PATH=data/diet_tracker.sqlite3
AGENT_PROFILE_PATH=data/agent.md

# 多维表格同步。先不配也能用，只会写 SQLite。
FEISHU_ENABLED=false
FEISHU_SYNC_MODE=api
FEISHU_BITABLE_APP_TOKEN=
FEISHU_BITABLE_TABLE_ID=
```

## 自定义 Agent 说明

你可以在服务器上创建：

```bash
mkdir -p data
cp docs/agent.example.md data/agent.md
```

然后编辑 `data/agent.md`，写你们的长期偏好、估算规则、常吃食物等。机器人每次调用模型估算时都会读取这个文件，不需要重建 Docker。

例如：

```text
小张午饭经常吃公司食堂，米饭默认按 180g 熟米饭估算。
小韩不喝含糖饮料，如果没特别说明，奶茶按无糖估算。
```

身份也可以直接在飞书里绑定，不用改 `.env`：

```text
我是小张
我是小韩
```

如果要让 CLI 写多维表格：

```env
FEISHU_ENABLED=true
FEISHU_SYNC_MODE=cli
FEISHU_BITABLE_APP_TOKEN=xxx
FEISHU_BITABLE_TABLE_ID=xxx
```

## 2. 启动

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

## 3. 飞书权限

至少需要：

```text
im.message.receive_v1 事件
读取用户发给机器人的单聊消息
接收群聊中 @ 机器人消息
获取群组中所有消息
以应用的身份发消息
获取与发送单聊、群组消息
获取消息中的资源文件
```

每次改权限后都要重新创建版本并发布。

如果希望“先在群里发图片，再 @机器人 看图”能工作，必须开通 `获取群组中所有消息`，scope 是 `im:message.group_msg`。这是飞书敏感权限；如果不申请它，机器人通常只能收到 @ 它的文字消息，收不到前面那张未 @ 的图片。

## 4. 数据持久化

`docker-compose.yml` 会把本地 `./data` 挂到容器 `/app/data`：

```text
./data/diet_tracker.sqlite3
./data/feishu_cli_media/
```

所以容器重建不会丢饮食记录。

## 5. 常见问题

### Missing LLM_API_KEY

说明 `.env` 没有配置硅基流动 key，或者 Docker Compose 没有读取到 `.env`。

检查：

```bash
docker compose exec diet-bot env | grep LLM
```

### 后台显示长连接失败

容器没有运行，或者事件监听进程退出了。

检查：

```bash
docker compose ps
docker compose logs -f
```

生产环境需要一直保持长连接。Docker 启动脚本默认使用：

```bash
tail -f /dev/null | lark-cli event consume im.message.receive_v1 --as bot --quiet | python -m diet_tracker.feishu_cli_bridge
```

这里不设置 `--timeout`。前面的 `tail -f /dev/null` 是为了在容器这种非交互环境里保持 stdin 打开，避免 `lark-cli` 因为 stdin EOF 自动退出。

### 机器人收不到消息

确认：

- 应用已发布
- 机器人已添加到群
- 群里消息要 `@机器人`
- 私聊机器人需要 `读取用户发给机器人的单聊消息`
