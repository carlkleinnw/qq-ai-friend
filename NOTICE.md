# 版权与授权范围

Copyright (C) 2026 carlkleinnw and contributors.

除明确标注的第三方内容外，本仓库作者有权授权的代码、配置、文档及本项目编写的预设，以 GNU Affero General Public License 第 3 版或任何后续版本发布，SPDX 标识为 `AGPL-3.0-or-later`。完整文本见 LICENSE。上述授权也适用于本项目此前发布版本中由本项目作者持有版权的相同内容，不改变已发布标签和安装包字节。

你可以按许可证使用、研究、修改及分发本项目；分发时保留许可证及版权声明，提供许可证要求的对应源码。如果修改后的程序通过网络与用户交互，应按许可证第 13 条向这些用户提供获取对应源码的方式。程序不提供适用性或其他担保；具体权利和义务以 LICENSE 原文为准。

## 第三方内容

- AstrBot 4.29.1 为 AGPL 项目。`scripts/repair_*.py` 中为兼容固定版本而保留的上游代码片段及其修改，继续遵循 AstrBot 的 AGPL 条款；AstrBot 原作者版权保留。上游来源：https://github.com/AstrBotDevs/AstrBot/tree/v4.29.1 。本仓库不声称拥有上游引擎的版权。
- NSIS、Conda、Python 依赖、FFmpeg 等保持各自许可证；Conda 相关文本位于 `installer/licenses`，其他说明见 THIRD_PARTY.md。安装包中的第三方二进制不因本声明而改用 AGPL。
- `private_companion` 与 `memory_companion` 源码不包含在仓库和安装 EXE 内，安装时从原作者固定提交下载。已锁定的 private_companion 未发现根目录 LICENSE；本仓库不授予这些插件额外的修改、商用或再分发权。使用或另行分发前应核对原作者条款，必要时取得授权。
- 社区角色名称、服务名称、商标与在线服务不在本项目授权范围内。本项目不隶属于 QQ、DeepSeek 或 AstrBot 官方。语音样例由 TTS 生成，不含参考视频录音。

## 对应源码

本项目源码：https://github.com/carlkleinnw/qq-ai-friend 。`v0.4.0` 对应发布的 Windows 安装包；构建步骤、依赖版本与来源见 `installer/README.md`、`installer/installer-lock.json`、`installer/conda-win64.lock`、`requirements.lock.txt` 和 `upstream.lock.json`。后续版本的第三方代码仍应从所标注上游获取。
