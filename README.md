# 万象助手 · 白歌排位 P0

为 `jkwind02-lang/wangxiangzs` 准备的升级层。以 `Cjy-CN/wanxiang-build` 的资料结构为基础，新增可运行的局面校验、模型接入、单次建议、回放和 Windows 桌面原型。

> **仓库交付：开发分支 `feat/baige-live-advisor`，通过 Pull Request 审核，不自动合并。** 上游固定快照由 `.github/workflows/import-upstream.yml` 导入，原始提交保留为导入提交的父节点；逐文件来源及校验值见 `UPSTREAM_IMPORT.json`。本助手的单元测试不是排位表现证明。
>
> **产品状态：回放优先、单次采集决策的开发原型，不是已实测的排位实时教练。** 没有自动跟踪全部画面变化、完整战斗模拟或胜率模型。未采集到的游戏变化无法自动使建议失效。

## 这一版实际增加了什么

| 模块 | 已实现 | 边界 |
|---|---|---|
| 局面数据 | JSON字段、唯一对象ID、时区、未知值、区域完整性检查 | 不把未看到当作不存在，不把未知当作0 |
| 白歌提醒 | 按带来源的社区快照提示合成进度与两种复制目标范围 | 不是当前版本已经实测的规则；不编随机概率 |
| 资料适配 | 从上游五类JSON中检索相关完整父记录，带类型、路径、指纹 | 缺资料/超出上下文预算时明确报告，不能靠卡名补写能力 |
| 模型接入 | Chat Completions兼容接口；可配置文本、视觉模型 | 需要自己的可用服务与凭据；本轮只进行了模拟接口测试 |
| 建议校验 | 单个下一步操作的对象区域、可见费用、能量、已实现目标规则检查 | 不模拟完整连锁或多步路线，不声称完整合法性 |
| 失效控制 | 编辑、换局面、新请求、超时、旧观察均可使建议失效 | 只能处理已观测到的变化；不是持续盯屏 |
| 桌面 | 加载局面、离线检查、模型建议、窗口选择、单次截图、视觉转录后人工确认 | Linux虚拟显示启动测试通过；Windows游戏采集未实测 |
| 隐私 | 显式联网确认、凭据仅从环境读取、本地记录默认关闭 | 发送截图可能包含昵称或聊天内容，须先检查 |

## 先在本地运行，不需要模型账号

要求 Python 3.11 或更高。推荐在源码目录运行；当前发行物不是已打包的 EXE/wheel。

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m wxq_assistant demo
py -3 -m wxq_assistant gui
```

`examples/baige_demo.json` 是**合成测试局面**。“示例英雄甲”等不是游戏卡牌；费用、回合、血量也不是实战证据。缺失英雄卡文时，联网模型的改变状态建议会被拦截。本地模式只做提醒，不伪装成大模型策略分析。

## 从你的仓库运行

直接克隆开发分支，不需要再次复制上游，也不要向已有的 main 强制推送：

```powershell
git clone --branch feat/baige-live-advisor https://github.com/jkwind02-lang/wangxiangzs.git
cd wangxiangzs
py -3 -m unittest discover -s tests -v
py -3 tools/verify_upstream.py
py -3 -m wxq_assistant demo
py -3 -m wxq_assistant gui
```

`skills/wanxiang-build/` 保留上游完整资料与原脚本，研究模式仍可单独使用。原始 README 在 `UPSTREAM_README.md`；新实战原型不会执行上游提示词作为程序指令。

`tools/prepare_repository.py` 是先前离线升级包的辅助导入器，用于另建本地目录，不是从本仓库运行的必要步骤。它只进行本地克隆、校验与暂存；不要用它覆盖本仓库的现有历史。

本分支的自动导入只允许固定来源和固定提交；不从任意输入执行远端代码。导入与升级都发生在开发分支，不自动合并到 main。

## 模型设置

程序不读取 ChatGPT/Codex 的登录 Cookie 或账号令牌，不自带凭据，也不自动加载 `.env` 文件。只使用你明确配置的模型服务。以下值须替换为服务中实际可用的地址、模型名和凭据：

```powershell
$env:WXQ_BASE_URL="https://api.openai.com/v1"
$env:WXQ_MODEL="你的文本模型名"
$env:WXQ_VISION_MODEL="你的视觉模型名"
$secret = Read-Host "仅在本机输入 API Key" -AsSecureString
$env:WXQ_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
py -3 -m wxq_assistant gui
```

不要把真实密钥写入库或发到聊天中。本地兼容服务可使用如 `http://127.0.0.1:8000/v1` 的地址；非本机地址必须 HTTPS。截图转录要求模型支持图像输入。

参数：

- `WXQ_TIMEOUT`：单次HTTP请求超时，默认12秒。
- `WXQ_OUTPUT_TOKENS`：输出上限，默认1400；复杂截图可能需要提高，否则截断会被明确拒绝。
- `WXQ_TOKEN_LIMIT_FIELD`：默认 `max_completion_tokens`；只支持旧参数的兼容服务可设为 `max_tokens`。
- `WXQ_JSON_MODE`：默认 `1`，使用JSON对象模式；服务不支持时可设 `0`，但返回仍须通过本地严格JSON验证。

这里的时间是程序设定的**失效阈值，不是响应速度保证**。决策请求预算默认15秒，live模式观察有效期默认30秒；分别在 `Session` 中配置。本轮没有真实模型、网络时延或额度成本实测。

命令行联网必须显式添加 `--online`：

```powershell
py -3 -m wxq_assistant analyze --state .\你的局面.json --mode replay --online
```

## Windows窗口采集与确认

安装可选依赖：

```powershell
py -3 -m pip install "Pillow>=11.2.1,<13"
```

打开桌面后依次选择窗口、单次采集，再决定是否将截图发送给视觉模型。识别结果先回到JSON区，**不能自动确认自己**。人工核对后点击“人工确认”，再运行本地检查或模型分析。

历史文件默认使用回放模式。确认不会把旧截图时间偷偷改成现在；实时模式下已过期的截图必须重新采集。画面改变后请重新采集，本版不能自动知道未观察到的商店刷新或买卖变化。

若遇到黑屏或窗口模式不兼容，采集会报错。不得因此改为读取进程内存、注入或绕过游戏保护。本工具不控制鼠标键盘、不自动买卖，不声称获得游戏官方许可。

`.local/` 保存用户主动采集的图片及可选日志，已被 `.gitignore` 排除；本包清单也不包含它们。

## 验证与后续

见 `docs/TEST_REPORT.md`、`docs/ARCHITECTURE.md`、`docs/NEXT_STEPS.md`。本轮测试不是上分证明，也不能代表建议的战略正确率。

上游来源及版本见 `UPSTREAM.json`。在已查询目录中未发现上游 LICENSE，本包不为其补写许可证、冒充原作者或把公开可读解释成任意再许可；对外分发及使用前需确认相应授权条件。
