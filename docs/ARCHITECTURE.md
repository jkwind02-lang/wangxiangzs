# P0设计与边界

## 目标

在不重写上游资料库的前提下，实现：明确的局面输入 → 相关卡文检索 → 模型提出下一步 → 本地检查 → 带失效控制的提示。使用者为Windows客户端排位玩家，首个专项棋手为白歌。

研究模式保留在上游Skill中；实时原型不每次运行整份长研究流程，也不把上游score.py的加权汇总当作战斗引擎。

## 模块

- `state.py`：输入协议、时间、完整性、唯一标识、快照指纹。
- `knowledge.py`：读取上游原始JSON，按类型及名称返回完整父记录，附SHA-256。不同类型同名不互相冒充。
- `rules.py`：只检查已实现的局部条件，区分blocked/conditional/informational。没有“完整验证通过”状态。
- `advisor.py`：封装模型任务、验证回复来源与快照、拦截不符合条件的建议。未通过建议不会保留在主建议区域。
- `client.py`：显式HTTPS/loopback请求、环境凭据、上限、错误脱敏、拒绝重定向。不执行模型输出中的代码。
- `capture.py`：Windows窗口枚举及指定HWND单次截图。仅使用可见窗口画面，不访问游戏进程数据。
- `vision.py`：可选图像转录；强制保留采集时间、关闭自动确认。
- `ui.py`：人工检查区、建议区、单次请求线程及主线程结果发布。

## 关键约束

1. 未知不等于0；区域不完整不能推断目标不存在。
2. 当前原型只建议下一步原子操作，未实现整套合成/卖牌序列模拟。
3. 随机选择权重、转瞬生命周期、连锁效果等未知项保留，不发明概率。
4. 模型引用来源ID存在只是格式证据，并不能证明模型正确理解了来源；仍需回放评估。
5. 未命中本局卡牌资料时，不发布改变状态的建议，改为检查信息。
6. 编辑、新快照、新请求和超时均会撤回旧建议；未采集画面变化则无法自动察觉。
7. 回放不重新伪造观察时间；实时建议检查快照时间与请求预算。
8. 模型失败时可继续本地检查，但不会以“本地模式”名义假装完成策略分析。

## 源码准备与权限

GitHub `create_file` 对目标仓库返回403，仓库读取仍为空。`permissions.push=true`只说明账号对仓库的能力，不等于当前集成的令牌具有内容写入授权。

本地准备工具克隆完整历史并固定提交；新main保留上游基线、开发分支叠加升级。仅在新目录操作，拒绝覆盖已存在的目标，不自动推送，不改变Git全局身份，不索取或查找账号凭据。

## 尚未实现

持续观察、帧差去抖、稳定图标识别、事件轨迹自动追踪、所有英雄规则引擎、战斗模拟、真实胜率估计、可靠模型路由和EXE打包。不要将这些当作本次已交付功能。

## 技术来源（接口参考，不代表实测结果）

- 上游原始资料：https://github.com/Cjy-CN/wanxiang-build/tree/8e854a4fcfe2527d846fa917d51c2c50ebafabb1
- Pillow窗口采集：https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html
- Tkinter事件与线程说明：https://docs.python.org/3/library/tkinter.html
- Chat Completions接口：https://platform.openai.com/docs/api-reference/chat/create
- GitHub权限错误：https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api#resource-not-accessible
