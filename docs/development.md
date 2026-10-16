# 开发指南

## 环境与首次运行

使用 Windows x64、Python 3.12 x64。Node.js 22 或以上用于 JavaScript 行为测试。GUI 和采集运行依赖见 `requirements.txt`；构建与测试环境统一安装 `requirements-build.txt`。

在仓库根目录执行 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe src\gui.py --demo
```

演示使用原创对白，不连接游戏，也不生成对白日志。真实采集运行 `src\gui.py`，在窗口中选择已适配的 `jshyl5.exe`，再点击“开始记录”。不需要把游戏复制进仓库。

## 目录与职责

| 路径 | 职责 |
| --- | --- |
| `src/agent.js` | 游戏进程内的对白调用边界、人物与正文原子事件 |
| `src/capture.py` | 连接、取消、有界队列与事件消费 |
| `src/dialogue.py` | 解码、事件去重和 TXT/JSONL 持久化 |
| `src/gui.py`、`src/ui_model.py`、`src/theme.qss` | Qt 工作线程、阅读交互、模型与主题 |
| `src/settings.py`、`profiles/` | 个人设置、资源路径和游戏版本校验 |
| `tests/` | 不连接游戏的行为测试 |
| `scripts/`、`JinshuDialogue.spec` | 文档检查、允许清单、许可收集与构建 |

数据流和并发边界见 [架构说明](architecture.md)。不要在 Frida 回调中执行文件写入或 UI 操作；不要直接从采集线程访问 QWidget。共享设置和记录路径由现有模块管理，不硬编码本机盘符。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\check_docs.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_agent.js
.\.venv\Scripts\python.exe src\gui.py --demo --smoke-test
```

无桌面的测试环境可以设置 `$env:QT_QPA_PLATFORM = 'offscreen'`；人工检查真实窗口前删除该环境变量。Qt 离屏测试会检查复制格式、历史滚动、路径设置、线程退出和单实例锁等行为，不能代替游戏适配验证。

调试原生入口时单独运行诊断探针，结束后再运行正式采集。两个工具同时安装同一入口的钩子可能触发签名保护。不要为排查问题关闭版本或入口签名检查。

## 构建与依赖变更

构建命令及验收清单见 [发布流程](releasing.md)。依赖升级同时更新锁定版本、构建脚本中的版本检查、第三方声明与许可缓存，重新验证独立解压启动。不要顺带格式化无关代码或引入没有实际用途的框架。
