# 第三方软件声明

金书对话录的项目代码采用 MIT 许可证。第三方软件、名称与商标保留各自权利；项目的 MIT 许可不替代下列许可。发行包的 `LICENSES/` 中包含原始许可文本、上游 attribution、依赖版本及带 SHA-256 的来源清单。

## 直接依赖与运行时

| 组件 | 本项目版本 | 许可与版权信息 | 官方来源 |
| --- | --- | --- | --- |
| Frida / frida-python | 17.23.3 | wxWindows Library Licence 3.1；Frida Developers。许可文本版权：Copyright (c) 1998–2005 Julian Smart, Robert Roebling et al。 | [Python bindings](https://github.com/frida/frida-python/tree/17.23.3)、[许可](https://github.com/frida/frida-python/blob/17.23.3/COPYING)、[Frida source](https://github.com/frida/frida/tree/17.23.3) |
| PySide6-Essentials / Qt for Python | 6.12.0 | 上游可选 LGPL-3.0-only、GPL-2.0-only 或 GPL-3.0-only；本发行采用 LGPLv3。Copyright The Qt Company Ltd. 及上游贡献者，逐文件声明见对应源码。 | [6.12.0 源码](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.12.0)、[官方许可说明](https://github.com/pyside/pyside-setup/blob/v6.12.0/README.pyside6_essentials.md) |
| shiboken6 | 6.12.0 | 与 Qt for Python 相同的上游开源许可选择；本发行采用 LGPLv3。Copyright The Qt Company Ltd. 及上游贡献者。 | [对应源码](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/sources/shiboken6?h=v6.12.0) |
| Qt Core / Gui / Widgets / Svg 与必要插件 | 6.12.0 | 本发行采用 LGPLv3；部分代码采用其他兼容许可，保留上游声明。Copyright The Qt Company Ltd. 及上游贡献者。 | [Qt Base 源码](https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v6.12.0)、[Qt SVG 源码](https://code.qt.io/cgit/qt/qtsvg.git/tree/?h=v6.12.0)、[Qt 许可](https://doc.qt.io/qt-6/licensing.html) |
| CPython 及其标准库组件 | 3.12 构建时使用的补丁版本 | PSF License Agreement 及 `Python-LICENSE.txt` 中保留的历史许可和组件声明。Copyright Python Software Foundation 及各组件作者。 | [Python 许可](https://docs.python.org/3/license.html)、[3.12 源码](https://github.com/python/cpython/tree/3.12) |
| PyInstaller bootloader（构建工具） | 6.22.3 | GPL-2.0-or-later 并附 bootloader exception；部分文件为 Apache-2.0。Copyright PyInstaller Development Team 及贡献者。 | [官方许可说明](https://pyinstaller.org/en/stable/license.html)、[对应源码与 COPYING](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |

`LICENSES/DEPENDENCIES.json` 记录实际构建环境中的版本。Frida wheel 自带的 `COPYING` 会原样收集；其中引用的 GNU Library GPL 允许采用后续版本，发行包同时附 GNU LGPLv3 与其引用的 GPLv3 正文。Qt wheel 随附的商业许可说明也保留，作为上游原始材料；本项目并不因此主张拥有 Qt 商业许可。

## Qt 内部第三方组件

Qt 的基础模块可能包含 zlib、libpng、LibJPEG-turbo、FreeType、HarfBuzz、PCRE2、double-conversion、Unicode 数据、哈希算法、TinyCBOR、平台绘制与辅助功能代码等。许可和版权因组件而异。`LICENSES/upstream/Qt-6.12.0/attributions/` 保留对应版本的原始 `qt_attribution.json` 及其引用的许可、版权文件；部分声明包含适用于其他平台的条目。`LICENSES/SOURCES.json` 给出每份文本的准确官方来源和校验值。

本软件的部分功能基于 FreeType 团队的工作：**Portions of this software are copyright © The FreeType Project (www.freetype.org). All rights reserved.** 完整条款见对应 FreeType 许可文件。

## 修改、替换与重建

本发行使用未作项目修改的官方 Python wheels，通过共享 DLL / Python 扩展使用 Qt 与 PySide6。允许为调试对 LGPL 组件的修改而进行逆向工程，不限制 LGPL 授予的修改权利。可在备份后将 `_internal/PySide6/`、`_internal/shiboken6/` 中的对应共享库替换为接口兼容的版本；也可使用随附源码包和公开构建脚本重建整个应用。替换应保持依赖版本、体系结构及文件布局兼容。

Qt / PySide6 / shiboken6 的对应 6.12.0 源码和构建文件可通过上述版本标签获取。上游仓库可按以下方式检出：

```text
git clone --branch v6.12.0 --depth 1 https://code.qt.io/qt/qtbase.git
git clone --branch v6.12.0 --depth 1 https://code.qt.io/qt/qtsvg.git
git clone --branch v6.12.0 --depth 1 https://code.qt.io/pyside/pyside-setup.git
```

重新分发二进制包时，须保留本声明和全部许可，并按 LGPL/GPL 等适用条款提供相应源码的获取方式；如修改第三方组件，还须提供相应修改。发布者应保留与实际二进制对应的上游源码副本或提供适用条款要求的源码交付方式。

Windows 系统库（包括此 Qt 构建使用的系统 ICU）由操作系统提供，不从开发用 Python 环境复制其他 ICU DLL；若构建工具收集 Microsoft Visual C++ 运行库，其版权及再分发条款仍由 Microsoft 保留，参见 [Microsoft 官方运行库说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

## 游戏内容

本项目及源码包不提供《金书红颜录》的程序、DLL、素材、对白或存档。游戏名称仅用于标明适配对象，相关权利属于原权利人。本项目不是游戏官方产品。
