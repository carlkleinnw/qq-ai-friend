# 第三方组件

本项目以现成组件配置和组合为主，未重写其对话、记忆、平台或调度实现。

| 组件 | 固定版本 / 提交 | 来源与许可说明 |
| --- | --- | --- |
| AstrBot | 4.29.1 | https://github.com/AstrBotDevs/AstrBot ，AGPL-3.0-or-later；实际运行代码来自同版本 PyPI wheel |
| private_companion | v6.7.0 / f2f87183993a0667800056f73bcf12df298cdbcb | https://github.com/menglimi/astrbot_plugin_private_companion ，保留原作者及元数据；所选版本未找到根目录 LICENSE，不能推断拥有再分发或商用授权 |
| memory_companion | v2.3.1 / fc13a00d38e3ccaa560d617f8cd22788250465ae | https://github.com/menglimi/astrbot_plugin_memory_companion ，保留原作者及元数据；按仓库实际条款核对使用范围 |
| edge-tts | 7.3.1 | https://github.com/rany2/edge-tts ，LGPL-3.0；在线语音服务自身并非本项目提供 |
| imageio-ffmpeg | 0.6.0 | https://github.com/imageio/imageio-ffmpeg ，包装代码与随附 FFmpeg 二进制分别遵循其许可 |

安装的第三方代码和二进制保存在本地 runtime，源码交付包不包含该目录，不将未明确授权的插件重新包装为自己的作品发布。完整安装依赖包含各自的许可证和元数据，见 Conda 环境的 site-packages。

2026-10-21：对已安装 memory_companion v2.3.1 的传统面板做了一处本地兼容修复，纠正编辑表单的权限、生命周期选项并保留未知值。原始 vendor 检出未修改；可审阅、重复执行的修复在 `scripts/repair_memory_panel.py`，具体原因与验证见 `docs/记忆管理.md`。未修改其记忆引擎或权限策略，源码包仍不包含插件源码。
