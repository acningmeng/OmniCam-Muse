# OmniCam Muse 模块

目标设备：PMA110 / Find X9 Ultra，相机 7.006.103。KernelSU 模块（ID `ricoh_pop_x9u`）配一个 LSPosed APK `omnicam-muse-<版本>.apk`，包名 `local.jiege.camera`。LSPosed 作用域：系统框架、相机、相册。

## 功能

- 理光 GR：GR 模式、影调、焦距条、快照对焦、相机与相册水印。
- POP：复古相机模式及资源、高像素；滑杆进成片，成片走 Ultra HDR。
- X10：清透、琥珀滤镜，调色盘及其成片调度（后置、人像、前置）。
- 大师模式：大师滤镜补全（徕卡 M9、富士 Rec.709 LUT，霓虹、和光），大师色彩（HNCS、Lumix、胶片、Canon、Darktable、Leica M9）。
- 自然模式、哈苏超清、普通模式 25MP 解禁、移轴模式、快门声。
- 设置在桌面或 LSPosed 中打开 APK。

各功能的原理与涉及文件见 `docs/MODULE.md`。

## 安装与回退

刷入模块并重启：刷入时模块安装包内 APK（`pm install -r -d`，结果写入模块目录的 `install.log`，签名不一致等失败不卸载已装应用），重启后相机、相册和系统框架都加载新版。同 ID 的模块原位更新。停用模块并重启即回退全部挂载。设置保存后相机下次读取即生效；快门声设置在铃声模式变化或重启相机后生效。

`post-fs-data.sh` 重建资源前，先延迟卸载本模块在 `/odm/etc/` 的配置与资源绑定，再从原厂目录合并资源，支持 KSU 软重启时重复执行。`/odm/lib64` 的库挂载由 Hybrid Mount 与 `post-mount.sh` 管理。


## 分层开关（x8u-rebuild 分支）

默认**只跑 L0（设备闸门 + 资源 staging + 日志）与 L1（符号层 hook）**，配置层全部关着。
每层一个标记文件，开了之后 `ksud soft-reboot`，再用 `tools/x8u_selftest.sh` 验收，通过了再开下一层：

| 层 | 标记文件 | 作用 | 验收 |
| --- | --- | --- | --- |
| L2 | `enable_config_binds` | `camera_unit_config` + `camera_unit_feature_config.protobuf` | `x8u_selftest.sh shoot`（照片模式） |
| L3 | `enable_algo_switch` | `oplus_camera_algo_switch_config`（POP/理光快门的前提） | `x8u_selftest.sh shoot`（POP、理光各一次） |
| L4 | `enable_occ_extras` | `oplus_camera_config` 的增补标签（调色板/GR 元数据） | 同上，另看 `iPaletteFlag` |
| legacy | `enable_legacy_configs` | 两份 X9 Ultra 构建的 aps/preview_decision | 一般不用 |

四个标记都还受 `MUSE_CONFIG_BINDS` 约束：非 X8U/X9U 机型（`MUSE_PROFILE=unknown`）或存在
`disable_config_binds` 时一律不绑，只留 LUT/资源层。

任何一层出问题：删掉对应标记文件 → `ksud soft-reboot` → 回到上一层，**不要**在运行期
`mount --bind` 换 `/odm/etc/camera/config/*`（相机 provider 在启动时就持有该文件，热换只会黑屏）。

`x8u_selftest.sh` 只读：`gate`（机型/固件/相机版本/标记）、`hooks`（LSPosed 是否注入相机与相册）、
`mounts`（哪几份配置在绑、合并目录是否完整）、`shoot`（按一次快门前后比对媒体库）、`all`。

## 灵感构图（本机启发式，x8u-rebuild 分支）

OPPO 相机的构图面板等的是一个 `com.oplus.aiunit.core.base.FrameDetector`，而这台机器的 aiunit
能力包里根本没有构图单元（`Detector/` 27 个、`OAA/` 里也没有 composition 模型），所以入口开了也一直
「无构图场景」。本分支不再依赖云端，改成在手机上自己算：

- `CompositionHeuristic`：Sobel 边缘能量质心 → 与三分法交点比较 → 输出 0–100 分、一句提示、一个归一化取景框。
  纯整数运算，`tools/offline_tests/CompositionHeuristicTest.java` 覆盖空帧/纯色/左三分/右边缘/居中 5 组。
- `CompositionBridge`：钩 `com.oplus.ocs.camera.OplusAICompositionHelper` 与
  `com.oplus.camera.aicomposition.OplusAIComposition` 里参数带 Bitmap/Frame 的方法，偷预览帧、500 ms 节流、
  按字段名把分数与提示写回结果对象。找不到类或字段就只记一行日志，原厂路径不动（fail-open）。
- 开关：Muse 设置里的「构图 → 灵感构图」（`ai_composition`，默认**开**）。打开后先由 `AiComposition`
  把 `realscene.support` / `inspiration.support` 两个配置位强制为真（入口从 GONE 展开的必要条件），
  再由 `CompositionBridge` 给面板打分。装了第三方云方案时把这一项关掉，两边不要同时改同一批配置位。

系统侧的三个「别做」：
- 不要 `killall lspd`（会把 zygote 拖死）；要停 hook 只在 LSPosed 管理器里改作用域。
- 不要用 `adb reboot` 代替 `ksud soft-reboot`（会丢临时 root）。
- 不要手改 `/data/adb/lspd/config/modules_config.db`（WAL 里存着 schema，只拷主库会把注册表写空）。
- `bind.log` 每次开机滚动成 `bind.log.prev`，看上一轮为什么没挂上要看 `.prev`。
