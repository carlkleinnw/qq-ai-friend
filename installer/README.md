# 安装器维护说明

用户说明见 [安装与更新](../docs/安装与更新.md)。本目录仅协调成熟组件，不另造安装、人格或备份系统。

- NSIS Unicode / Modern UI 2：标准向导、目录选择、快捷方式、应用列表和卸载。
- 官方 conda-standalone 26.7.0、`conda-win64.lock`、`requirements.lock.txt`：独立、固定依赖的 Python 3.12 环境。
- AstrBot 4.29.1：面板、账号设置、QQ 接入、人格、路由、原生备份导入导出。
- 固定提交的原始插件及固定版本面板：安装时下载并核验 SHA256。未明确授权的插件源码不嵌入 EXE，其许可仍需在进一步分发前核对。
- `launcher.cs`：无控制台的薄启动器，用 Windows 自带 .NET Framework 编译器构建。

根目录为清单管理的程序；runtime 为数据、环境、缓存、日志、登记与备份。大体积下载与缓存均放所选目录。Conda 及依赖的许可证在 licenses。

## 构建

需要 Windows x64、Python 3.12、NSIS 3.12+ 和锁定的 conda-standalone EXE。先检查空间，工具下载到非 C 盘。

```powershell
python installer/build.py --version 0.4.2 --compiler "E:/DeveloperTools/nsis-3.12/NSIS/makensis.exe" --conda "E:/DeveloperTools/conda-standalone-26.7.0/standalone_conda/conda.exe" --output "dist/AI好友_Setup_0.4.2.exe"
```

构建器校验 Conda EXE，按明确允许的源码目录生成逐文件哈希清单、载荷和 EXE SHA256。runtime、dist、测试、截图和私人账号不进入载荷。构建期间不要编辑源码；本版未统一时间信息，不宣称逐字节可复现。

## 升级约定

环境标识由 Conda / pip 清单和引擎补丁计算；依赖或补丁改变时创建新环境，保留旧环境。业务代码变更可复用环境。部署锁和服务锁避免同目录冲突；覆盖前检查旧文件哈希，拒绝覆盖手工修改和未登记开发数据。

切换前停止所属服务，备份旧程序、指针及 AstrBot 原生数据；幂等初始化保留用户设置；首次才配置新账号。检查通过才登记新版本，失败尝试恢复旧代码、指针和服务。回退代码不自动倒退数据库。

`data_format` 是兼容承诺。更换引擎、数据结构、上游插件或既有修复方式前，先做兼容审查与隔离迁移验收；不兼容时提升该字段并提供迁移工具，不能绕过检查。当前无正式更新源，不硬编码虚构地址，先通过同源新版 EXE 更新。

发布前运行完整项目测试、PowerShell 语法检查与凭据检查；独立目录实测 EXE 首装、空密钥 / QQ、保留数据升级、故障恢复、版本回退、卸载保留及同位置重装。QQ 与收费模型验证使用另行确认的测试账号，不把开发者 runtime 当发行载荷。

参考：[NSIS](https://nsis.sourceforge.io/Main_Page)、[conda-standalone](https://github.com/conda/conda-standalone)、[Conda 环境](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html)、[AstrBot](https://github.com/AstrBotDevs/AstrBot)。
