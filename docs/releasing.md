# 发布流程

正式发布需要维护者明确决定，CI 只测试和生成 artifact，不自动公开 Release。以下命令在仓库根目录的 PowerShell 中运行，需要 Windows x64 和已登录的 GitHub CLI。

## 版本与材料

使用 `vMAJOR.MINOR.PATCH` 标签。发布前核对 `src/settings.py`、`scripts/build.ps1`、`scripts/package_source.py`、GitHub workflow 的版本和文档中的文件名一致；将 CHANGELOG 的 Unreleased 内容整理到带日期的正式版本。

新依赖或依赖升级需要同步第三方声明、官方许可缓存及 `scripts/licenses/SOURCES.json` 的版本、来源和哈希。不能只更改依赖版本而沿用未经核对的材料。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe scripts\check_docs.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_agent.js
.\.venv\Scripts\python.exe src\gui.py --demo --smoke-test
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

构建在 `release/` 生成免安装 ZIP、源码 ZIP 和 `SHA256SUMS`。不要把整个开发目录打包，也不要从已经游玩使用的解压目录重新压缩发布。

发布前检查：

- 将 ZIP 解压到独立目录，清空开发用 PYTHONHOME/PYTHONPATH 和 PATH 后启动。保持完整 `_internal/` 结构，确认正常界面与演示可以退出。
- 核对游戏路径选择、停止采集、复制、历史阅读、文件保存及可写目录回退。原生适配有变化时重新做游戏实测，记录范围。
- 核对源码 ZIP 与当前提交一致，包含全部公开文档；排除游戏、私人设置、对白、诊断、环境和内部计划。
- 确认许可文本、SHA256SUMS 及本次提交的 Windows CI 结果。当前 Windows Qt 构建使用系统 ICU，不能捆入其他 Python 发行版中符号不兼容的 `icuuc.dll`。

## 创建 Release

先把已验证的提交推到 `main` 并确认 CI 通过，再使用确定的提交 SHA 创建标签和 Release。发布说明按 [模板](release-notes-template.md) 准备为本地临时文件：

```powershell
$releaseCommit = git rev-parse HEAD
git tag -a v0.3.1 $releaseCommit -m 'Release v0.3.1'
git push origin v0.3.1
gh release create v0.3.1 --repo 460649891/jinshu-dialogue --target $releaseCommit --verify-tag --title '金书对话录 v0.3.1' --notes-file release\release-notes.md
gh release upload v0.3.1 --repo 460649891/jinshu-dialogue release\JinshuDialogue-0.3.1-windows-x64.zip release\JinshuDialogue-0.3.1-source.zip release\SHA256SUMS
```

`--verify-tag` 要求已推送的标签存在。后续版本替换示例中的标签和文件名；不要覆盖已经公开的标签或同名资产，修复应发布新补丁版本。

发布后打开下载链接，核对附件名称、大小与 SHA-256，确认默认 README 中的最新版本入口可用。不要把本地演示或未来计划写成已交付功能。
