# AstrBot + NapCat QQ 机器人部署包

把 QQ 客户端接成 OneBot v11，用 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 跑对话逻辑，
再配一个任意 OpenAI 兼容的大模型（示例是 DeepSeek）。附带三个自用插件：

| 插件 | 作用 |
| --- | --- |
| `astrbot_plugin_face_sender` | 把模型输出里的 `[[face:14]]` 变成 QQ 小黄脸，`[[bqf]]` / `[[bqf:关键词]]` 变成表情包图片 |
| `astrbot_plugin_group_chatter` | 群聊节奏控制：普通话题 3~4 句回一次、被 @ 必回、对上话后自由发挥、区分说话人、可 `%%SKIP%%` 不接、两次回复间隔 |
| `astrbot_plugin_memory` | 长期记忆：`记住 xxx` / `忘记 xxx` / `/记忆列表`，自动注入对话 |

```
.
├─ start_all.bat / stop_all.bat          一键启动 / 停止
├─ NapCat/
│  ├─ StartBot-Admin.bat                 提权启动（会弹 UAC）
│  ├─ StartBot.bat                       实际启动 QQ + 注入
│  ├─ elevate.ps1                        提权脚本
│  └─ config/onebot11.example.json       反向 WS 指到 AstrBot 的示例配置
├─ AstrBot/
│  ├─ start_astrbot.bat                  前台启动
│  ├─ start_astrbot_hidden.bat           后台启动（计划任务用）
│  └─ data/plugins/                      三个插件的源码
└─ scripts/
   ├─ persona.txt                        人设正文
   ├─ persona_extra.txt                  人设补充（含 {OWNER_QQ} 占位符）
   └─ apply_persona.py                   把人设写进 AstrBot 数据库
```

## 部署步骤

1. **装 QQ**：桌面版 NTQQ，记下安装路径（下面以 `D:\QQ.exe` 为例）。
2. **装 AstrBot**（建议 Python 3.12）：按官方文档源码部署，能跑起 `main.py` 即可。
3. **放插件**：把 `AstrBot/data/plugins/` 下的三个目录拷进你的 AstrBot 的 `data/plugins/`。
4. **放 NapCat**：下载 [NapCat.Shell.zip](https://github.com/NapNeko/NapCatQQ/releases)，解压到 `NapCat/`，
   然后把本仓库 `NapCat/` 下的 `StartBot*.bat`、`elevate.ps1` 覆盖进去（用于带日志的启动）。
5. **配 OneBot**：把 `NapCat/config/onebot11.example.json` 复制成
   `NapCat/config/onebot11_<你的机器人QQ>.json`，它会把事件反向 WS 推到 `ws://127.0.0.1:6199/ws`。
6. **配 AstrBot**：WebUI 里添加 `aiocqhttp` 平台（监听 6199，路径 `/ws`），再配好模型服务商。
7. **配人设与主人号**：
   ```bash
   # scripts/config.local.json（不要提交）
   {"owner_qq": "你的QQ"}
   python scripts/apply_persona.py AstrBot/data/v4.db scripts/persona.txt scripts/persona_extra.txt AstrBot/data/cmd_config.json
   ```
   注意实际的数据库路径按你的 AstrBot 版本调整。
8. **启插件配置**：把各插件目录下的 `config.example.json` 复制为 `config.json`，
   填上 `admin_ids`、`sticker_dir` 等；没配 `sticker_dir` 时表情包功能自动关闭。
9. **启动**：双击 `start_all.bat`（或 `NapCat/StartBot-Admin.bat`），用手机 QQ 扫码登录。

## 需要自己填的占位符

| 占位符 | 位置 | 说明 |
| --- | --- | --- |
| `{OWNER_QQ}` | `scripts/persona_extra.txt` | 主人 QQ，`apply_persona.py` 会自动替换 |
| `YOUR_QQ` | `AstrBot/data/plugins/astrbot_plugin_memory/config.example.json` | 允许使用记忆命令的 QQ |
| `""`（sticker_dir） | `AstrBot/data/plugins/astrbot_plugin_face_sender/config.example.json` | 表情包目录 |
| 模型 API Key | AstrBot WebUI → 服务提供商 | 不要写进仓库 |

## 插件行为速查（group_chatter）

- 被 @ / 提到 `keywords` 里的词：必回；
- 普通群消息：每 `min_gap ~ max_gap`（默认 3~4）条给一次接话机会，模型可输出 `%%SKIP%%` 放弃；
- 别人之间的提问（没问你）：每 `other_question_gap`（默认 6）条才给一次机会；
- 和你对上话后：进入自由聊天，`engage_ttl_seconds`（默认 120s）内不节流；
- 每条回复生成后先停 `min_reply_interval_seconds`（默认 6s）再发；等待期间的新消息会排到这条发完再判断；
- 群聊记录按「昵称(QQ号)」持久化到 `group_memory.json`，重启不丢。

## 注意

- 本仓库只放代码和模板，**不包含任何真实 QQ 号、API Key、面板密码或聊天记录**；
- 部署后 `config.json`、`memories.json`、`group_memory.json`、`onebot11_<QQ>.json` 都属于本地隐私文件，已在 `.gitignore` 里排除；
- NapCat 会向 QQ 客户端注入 hook，属于第三方非官方方案，存在账号风险，请自行评估。
