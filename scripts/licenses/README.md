# 官方许可缓存

这些文件只含第三方许可、版权与 attribution，不含游戏内容。构建读取本目录，无需联网。

- Qt/PySide6 对应 6.12.0；文本从 `code.qt.io` 官方版本标签取得。
- `SOURCES.json` 为 UTF-8 清单，记录逐文件官方 URL、版本和 SHA-256。缓存保持上游原始字节；没有扩展名的上游文本在本地追加 `.txt`。
- Frida 的 wxWindows COPYING、Python 许可和 PyInstaller 许可从构建环境的安装包中原样收集。
- LGPLv3 正文应与 GPLv3 一起保留。Qt attribution 文件由上游维护，部分是允许原始换行的 QDoc JSON，不能假定全部符合严格 JSON 解析器要求。
- 缓存更新后须重新核对版本、来源和 SHA-256，并执行 `package_source.py --collect-licenses` 验证。

包中的 Qt 对应源码获取、动态库替换及重建说明见项目 `THIRD_PARTY_NOTICES.md`。
