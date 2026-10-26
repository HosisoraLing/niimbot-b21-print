# 第三方来源与许可证说明

## 本项目的许可证与原创归属

项目名称：**精臣 B21 蓝牙打印**
项目仓库：<https://github.com/HosisoraLing/niimbot-b21-print>

本项目自行编写的代码采用 **GNU Affero General Public License, version 3 only**（SPDX 标识符：`AGPL-3.0-only`），不包含“或任何更新版本”的授权。项目源码公开提供；完整许可证见 [LICENSE](<LICENSE>)。

Copyright (C) 2026 HosisoraLing and contributors

上述原创归属不替代第三方材料的原有版权归属。本项目保留下述上游材料及可能的衍生部分适用的 MIT 版权、许可和免责声明。GNU 官方许可证文件保持原文，其中“How to Apply”部分的示例不是将本项目许可变更为 `AGPL-3.0-or-later` 的声明。

本项目为非官方工具，与 NIIMBOT 或相关软硬件厂商无隶属、赞助或认可关系。NIIMBOT、精臣等名称仅用于说明兼容设备；相关商标及其他权利归各自权利人。

## 1. NiimBlueLib

- 项目：MultiMote/niimbluelib，作者 MultiMote。
- 仓库：<https://github.com/MultiMote/niimbluelib>
- 参考范围：B1PrintTask 打印任务流程、协议封包与通信实现、BLE 服务 UUID 等信息。相关逻辑在本项目中以 Python 实现；本项目不捆绑该 TypeScript 库的完整实现。
- 实际参考及本次核查快照：`a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe`。
- 上游许可证：MIT；版权原文为 `Copyright (c) 2024 MultiMote`。
- 随附完整许可证：[niimbluelib-MIT.txt](<licenses/niimbluelib-MIT.txt>)。
- 原始许可证：<https://raw.githubusercontent.com/MultiMote/niimbluelib/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/LICENSE>
- 原始 README：<https://raw.githubusercontent.com/MultiMote/niimbluelib/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/README.md>
- 包元数据（标明 `MIT`）：<https://raw.githubusercontent.com/MultiMote/niimbluelib/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/package.json>

参考源码：

- [B1PrintTask.ts](<https://github.com/MultiMote/niimbluelib/blob/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/src/print_tasks/B1PrintTask.ts>)
- [protocol.ts](<https://github.com/MultiMote/niimbluelib/blob/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/src/packets/protocol.ts>)
- [bluetooth_impl.ts](<https://github.com/MultiMote/niimbluelib/blob/a9bc3f5c20c95e3a31ea3f5f2302ce7b27c34abe/src/client/bluetooth_impl.ts>)

### 上游 README 的用途警告

上述 README 的 WARNING 原文为：

> This project is intended for informational and educational purposes only.
> The project is not affiliated with or endorsed by the original software or hardware vendor,
> and is not intended to be used for commercial purposes without the consent of the vendor.

中文释义：该上游项目表示其仅用于信息与教育目的，不隶属或获原软硬件厂商认可，并表示未经厂商同意不拟用于商业用途。此处的 vendor 指原软硬件厂商。

同时，该快照的 LICENSE 是标准 MIT，明文包含不受限制地处理软件及销售软件副本的授权，未包含非商业条款；包元数据也标明 MIT。因此，README 的上述表述与 LICENSE 的宽泛授权存在文本张力。本说明如实披露二者，不判断该警告的法律效力、优先级，或具体用途是否必须获得厂商同意，也不擅自将上游许可证改称“MIT-NC”。

**这段披露不是给本项目新增“仅限教育”或“禁止商业使用”的许可条件。** 本项目自行编写的代码仍按 `AGPL-3.0-only` 提供，上游材料保留其 MIT 通知。许可证不能被解释为厂商已授权或背书，也不意味着已解决所有第三方权利问题。有商业使用计划时，建议向上游维护者取得书面澄清，并在需要时就商标、专利、合同及适用法域等问题寻求独立专业意见。

## 2. niimprint

- 项目：AndBondStyle/niimprint。
- 仓库：<https://github.com/AndBondStyle/niimprint>
- 原始开发者：kjy00302；fork 与增强：AndBondStyle，依上游 README 记载。
- 参考范围：`niimprint/printer.py` 中的协议及打印流程。本项目不捆绑该库的完整实现。
- 最初参考地址：<https://raw.githubusercontent.com/AndBondStyle/niimprint/master/niimprint/printer.py>。这是可变分支地址，未记录当时对应的 commit。
- 本次核查的 `main` 固定快照：`35c41a705cbc25ded388f1d562f184bf8994080e`。该快照用于核查许可证与来源，**不保证就是最初参考的版本**。
- 上游许可证：MIT；版权原文为 `Copyright (c) 2023 kjy00302`。
- 随附完整许可证：[niimprint-MIT.txt](<licenses/niimprint-MIT.txt>)。保留原有版权行，不将其替换为 fork 维护者署名。
- 原始许可证：<https://raw.githubusercontent.com/AndBondStyle/niimprint/35c41a705cbc25ded388f1d562f184bf8994080e/LICENSE>
- 原始 README：<https://raw.githubusercontent.com/AndBondStyle/niimprint/35c41a705cbc25ded388f1d562f184bf8994080e/readme.md>
- 核查的源码：[printer.py](<https://github.com/AndBondStyle/niimprint/blob/35c41a705cbc25ded388f1d562f184bf8994080e/niimprint/printer.py>)。

## 3. 通知的保留与范围

上述 MIT 许可证要求，在软件副本或实质部分中保留相应版权及许可通知。本项目随附两份上游完整许可证（包括免责声明），作为对参考、移植或改编部分的保守来源与合规记录；仅因没有捆绑完整库，不能据此推定没有通知保留义务。将实现从 TypeScript 改写为 Python 本身也不等于证明没有使用上游代码表达。

该来源说明不表示协议事实、命令值或 UUID 本身必然受版权保护，也不是关于本项目采用范围或法律性质的最终认定。上游材料及可能的衍生部分的 MIT 通知不因本项目的 AGPL 许可声明而被删除或替代。再分发时请保留适用的上游通知及相应许可全文，并遵守本项目适用的 AGPL 条款。

## 4. 外部依赖与字体

- **Pillow**：图像处理依赖；项目地址 <https://github.com/python-pillow/Pillow>。
- **Bleak**：BLE 通信依赖；项目地址 <https://github.com/hbldh/bleak>。

Pillow 与 Bleak 在本项目中仅作为依赖声明，由使用者另行安装；本仓库不捆绑它们的源码或二进制发行包。本说明不将这些依赖重新许可为 AGPL，其使用和再分发应遵守各自版本适用的许可证。若后续制作包含依赖的发行包，应按实际分发版本另行核查并附带所需通知。

本仓库不捆绑字体文件。使用者自行提供或选择的系统字体，适用各自的字体许可；本项目的源码许可证不授予字体权利。

## 5. 核查记录与边界

核查日期：2026-10-26。依据上述 GitHub 固定快照的原始 LICENSE、README 和相关源码进行来源记录；NiimBlueLib 的 `package.json` 亦标明 MIT。本说明不构成对全部仓库历史、全部文件或全部法域的法律审计，不对商业用途或其他第三方权利作法律保证。许可证的完整条款以随附原文为准。
