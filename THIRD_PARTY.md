# 第三方组件

本项目以现成组件配置和组合为主，未重写其对话、记忆、平台或调度实现。

0.4.2 的 QQ 底部人设菜单使用已安装 botpy SDK 的 HTTP 客户端、AstrBot 原生鉴权插件 API 和 QQ 官方 `/v2/menu` 接口，未增加依赖或复制第三方菜单插件。结构和限制见 [官方查询文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_menu.get.html) 及 [官方修改文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_menu.put.html)。只扩展本项目的人设菜单，保留其他已有菜单；人设保存仍走原生人格与既有私聊授权。

具名自定义预设继续复用 AstrBot PersonaManager：设定内容存入原生人格表，名称及引用由原生插件配置保存。网页输入窗口使用浏览器内置 dialog；未引入独立数据库、表单框架、外部网页服务或公网访问入口。新增预设同步到 QQ 官方菜单，每五项分组，保持已有无关菜单和用户编辑权限。

本项目自身授权见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE.md)。第三方代码、二进制及服务保持各自条款，本项目的 AGPL 声明不替代其授权。

0.4.0 的 Windows 安装器复用 NSIS Modern UI 2、官方 conda-standalone 26.7.0 和 Windows 自带 .NET Framework。Conda 可执行文件采用固定 SHA256，许可证和依赖许可证保留在 installer/licenses。上游陪伴 / 记忆插件从原始仓库按固定提交下载并校验，不嵌入安装 EXE。安装器不代表上游插件获得新的分发授权。构建、来源与升级约定见 installer/README.md。

| 组件 | 固定版本 / 提交 | 来源与许可说明 |
| --- | --- | --- |
| AstrBot | 4.29.1 | https://github.com/AstrBotDevs/AstrBot ，AGPL-3.0-or-later；实际运行代码来自同版本 PyPI wheel |
| private_companion | v6.7.0 / f2f87183993a0667800056f73bcf12df298cdbcb | https://github.com/menglimi/astrbot_plugin_private_companion ，保留原作者及元数据；所选版本未找到根目录 LICENSE，不能推断拥有再分发或商用授权 |
| memory_companion | v2.3.1 / fc13a00d38e3ccaa560d617f8cd22788250465ae | https://github.com/menglimi/astrbot_plugin_memory_companion ，保留原作者及元数据；按仓库实际条款核对使用范围 |
| edge-tts | 7.3.1 | https://github.com/rany2/edge-tts ，LGPL-3.0；在线语音服务自身并非本项目提供 |
| imageio-ffmpeg | 0.6.0 | https://github.com/imageio/imageio-ffmpeg ，包装代码与随附 FFmpeg 二进制分别遵循其许可 |

安装的第三方代码和二进制保存在本地 runtime，源码交付包不包含该目录，不将未明确授权的插件重新包装为自己的作品发布。完整安装依赖包含各自的许可证和元数据，见 Conda 环境的 site-packages。

2026-10-21：对已安装 memory_companion v2.3.1 的传统面板做了一处本地兼容修复，纠正编辑表单的权限、生命周期选项并保留未知值。原始 vendor 检出未修改；可审阅、重复执行的修复在 `scripts/repair_memory_panel.py`，具体原因与验证见 `docs/记忆管理.md`。未修改其记忆引擎或权限策略，源码包仍不包含插件源码。

大肥鱼表达风格参考 ERUIHNIYHBKBNF 的 [dafeiyu-persona](https://github.com/ERUIHNIYHBKBNF/dafeiyu-persona)（仓库标注 MIT）。只借鉴社区角色特征，自行编写短提示词和示例，未安装该 skill 或打包其源码。声音使用现有 edge-tts 与 AstrBot 原生适配器，不包含视频原声、第三方录音或新声音模型。

0.1.1 本机稳定性修复对已安装 AstrBot 4.29.1 的 Edge TTS 超时、原生一次性提醒失败保留与启动恢复、原生备份提醒表覆盖做了最小修改。固定原文件摘要与可复查替换规则分别在 repair_tts_timeout.py、repair_cron_failure.py、repair_backup_coverage.py；原文件在 runtime/backups。继续使用原有重试、调度、导入导出和 SDK，不分发完整第三方源码。新增消息防重插件是本项目的原生事件钩子，使用标准库 SQLite 唯一约束；启停锁复用已锁定的 filelock，未增加依赖。

指定上游测试的兼容检查在私有副本进行，原始检出和生产陪伴插件未修改；四个经审查的事件局部/生命周期钩子用 AST 摘要固定，避免以后误用同一排除结论。具体修正和结果见 scripts/check_upstream_compat.py 与 docs/稳定性验收.md。

0.2.0 人设功能直接复用 AstrBot 的原生 Plugin View、鉴权、PersonaManager 与数据库。本项目新增薄表单适配和四种原创短预设；参考 SillyTavern 官方角色设计说明的组织方式，未复制其代码或打包其前端。研究了 Persona+ 的方案但未安装或复制其代码：QQ 资料同步仅支持 NapCat，与当前官方接入不兼容。来源与取舍见 docs/人设功能.md，没有新增第三方依赖。

0.3.0 QQ 人设指令复用 AstrBot 的 command 过滤器、事件回复与停止机制、管理员判断，以及同一个原生人格保存入口。仅新增授权私聊检查和十分钟内存草稿确认，未引入新平台适配器、模型、数据库或依赖。预设已追加体贴甜蜜女友，当前为五种。
