# OmniCam Muse 模块

目标设备：PMA110 / Find X9 Ultra，相机 7.006.103；已适配 PKU110 / Find X8 Ultra，相机 7.006.123、相册 `com.coloros.gallery3d`。KernelSU 模块（ID `ricoh_pop_x9u`）配一个 LSPosed APK `omnicam-muse-<版本>.apk`，包名 `local.jiege.camera`。LSPosed 作用域：系统框架、相机、相册。

## 设备档案（Find X8 Ultra）

移植到别的机型不是改常量，而是让模块带着目标机自己的档案上线。`module/profiles/x8u/` 下四份 JSON 由
`tools/profiles/gen_x8u_profiles.py --dump <dump>` 从真机 dump 生成，里面的路径、字节数、摘要全部来自 dump
与仓库，没有手写值：

- `device.json`：机型、系统构建、相机/相册包名与 APK 摘要、SDK jar 摘要与缺失的调色盘类。
- `mounts.json`：每个 bind 条目的源/目标/门闸/期望状态，运行期拷贝层（7 项）、写进 shared_prefs 的 15 个键、以及
  Pro 视频 ISZ 补丁的实测行数与列数。
- `deltas.json`：以本机原厂配置为 base（导出在 `base/` 下并带摘要），X9 Ultra 独有的 22 条条目、preview decision
  的 POP 分支；`untouched` 列出四个跨机型不可合并的配置及原因。
- `resources.json`：LUT / basictone / gamma / ISP 资源的文件数、字节数与聚合摘要。

`tools/profiles/build_x8u_payload.py` 按 `deltas.json` 从 base 重新合成 payload（`--check` 验证磁盘与清单一致，
并确认重新合成的字节与仓库一致），`tools/profiles/check_x8u_package.py --zip ... --dump ...` 把成品包与档案、dump
三方交叉校验（脚本语法、payload 摘要、22 条增量、四个已移植符号名、bind 目标是否真在目标机上）。`tools/port_x8u_config.py`
已被上面这套流水线取代，仅保留为一次性迁移脚本。

X8U 上的实际绑定量（`mounts.json` 的 `expectedSummary`）：可以挂的 10 项 = 两个已按本机原厂文件重基的配置
（`camera_unit_config`、`oplus_camera_preview_decision_config.json`）、**X9 Ultra 的 feature 表**
（`camera_unit_feature_config.protobuf`，本机表里没有 `gr_photo` / `retro_camera` / `tilt.shift` / `ai_composition`
任何一条，不挂它 GR 与移轴根本不会出现在相机里；它同时是 `UnmountedGuard` 的挂载探针）、**按本机原厂表重建的 APS
模式表**（`oplus_camera_algo_switch_config`，见下）、音频曲线、meishe LUT 合并目录、basictone 合并目录、三份 gamma。跳过 4 项 = `com.qti.tuned.lighthouse*.bin`（本机是 `com.qti.tuned.zf*`，
绑定等于把别的镜头调优套上来）。另外两个配置（`oplus_camera_config`、`oplus_camera_aps_config`）仍是 X9 Ultra 构建，
比本机原厂旧，默认不 bind；需要时 `touch $MODDIR/enable_stale_config_binds` 才挂。

## POP / 理光的快门为什么需要那张 APS 模式表

快门点了没反应，问题不在触摸也不在 LUT。`/odm/etc/camera/config/oplus_camera_algo_switch_config` 是 APS 记录
「哪些模式有预览结果」的唯一地方：`AlgoSwitchConfig.sPreviewConfigMap` 以 `<mode>@<cameraId>` 为键，查不到就是
null，APS 不出结果，`BaseMode.m8()` 于是把这次快门拒掉，`bb.g.b` 停在 -1 —— 按钮是可点的、点击也进来了，就是
不会下发 capture 请求。本机原厂表里 21 个 capture 模式、36 个 preview 模式，`retroCamera` 一个都没有（POP 是
X8 Ultra 唯一缺的模式），所以 POP 预览能出、快门永远不响应；理光同理由同一张表决定。

`tools/build_x8u_algo_switch_config.py` 把本机原厂表解码（`01 01` 信封 + AES-ECB，key 取自 `libOplusSecurity.so`
+0x7AB）、去掉 `//` 注释，再把 X9 Ultra 表里的 `retroCamera` capture/preview 两个块插到 `common` 之后，输出明文
JSON。实测：绑定后 POP 与理光都能正常出片（媒体库 `_id` 连续增长）。

这张表必须在**开机时**绑：运行期对 `/odm/etc/camera/config/*` 做 `mount --bind` 会让相机 provider 拿着旧 inode，
表现为取景黑屏、快门全废；即使绑回原厂文件也一样。改完这张表要 `ksud soft-reboot`，不要热换。

开关（改完不用重编）：

- `disable_config_binds`：不 bind 任何相机配置，只跑 LUT 与钩子层。
- `enable_stale_config_binds`：额外 bind 上面那四个 X9 Ultra 构建的配置（默认关闭，因为本机版本更新）。
- `disable_pro_video_isz`：跳过 Pro 视频 ISZ 的就地补丁（本机布局与 X9 Ultra 不同，本来会自动跳过）。
- `enable_algo_interface`：bind 模块自带的 `libAlgoInterface.so`（颗粒跳板按 X9 Ultra 构建手写，换机型前先重推导偏移）。
- 库与 ISP 调优都是按目标存在才挂：X8 Ultra 没有 `libBasicTonePhotoX9/X10.so`，所以 8,960 B 的 router 不会覆盖
  原厂 538,400 B 的实现，`libmsnativefilter.so` 也不绑。

## 灵感构图

相机 APK 自带整套实现：`com.oplus.camera.feature.aicomposition` 下 534 个类型（view 391 / inspiration 116 /
state 5）、`/odm/etc/camera/apk_resources/mp4` 的 4 段入口引导视频、以及 `AICompositionFeatureKeys` 的 6 个
DataKey（`key_ai_composition`、`ai_composition_last_mode` 等）。缺的只是 feature 表里没有
`com.oplus.camera.feature.ai_composition` 这一条，所以总闸返回 false、入口不出现。

这个总闸不是机型白名单：`com.oplus.camera.util.AndroidTestAdapter.isSupportAIComposition()` 只有六条指令——
查一次 feature 表、判 null。`hook/composition/AiComposition.java` 把总闸和 `getAICompositionState` 都置 true；
开关状态仍是原厂 DataKey `key_ai_composition`，由 `service.sh` 写入 `override_config_data.xml`，所以相机里的
开关照旧读写同一个位置。Muse 设置里的「灵感构图」开关关掉后，下次相机启动就不再挂钩。

边界：这里只开入口。构图推理在 `com.oplus.aiunit`（独立的可更新 APK，走 `AIUnitService` / `IUnit` 私有 AIDL），
灵感库带账号和网络（`AICompositionAccountManager`、`InspirationNetwork*`、`AICompositionDeepThink`）。这些不在
钩子范围内；服务不可用时入口能打开但分析不会返回。

## 功能

- 理光 GR：GR 模式、影调、焦距条、快照对焦、相机与相册水印。
- POP：复古相机模式及资源、高像素；滑杆进成片，成片走 Ultra HDR。
- X10：清透、琥珀滤镜，调色盘及其成片调度（后置、人像、前置）。
- 大师模式：大师滤镜补全（徕卡 M9、富士 Rec.709 LUT，霓虹、和光），大师色彩（HNCS、Lumix、胶片、Canon、Darktable、Leica M9）。
- 自然模式、哈苏超清、普通模式 25MP 解禁、移轴模式、快门声、灵感构图入口。
- 设置在桌面或 LSPosed 中打开 APK。

各功能的原理与涉及文件见 `docs/MODULE.md`。

## 安装与回退

刷入模块并重启：刷入时模块安装包内 APK（`pm install -r -d`，结果写入模块目录的 `install.log`，签名不一致等失败不卸载已装应用），重启后相机、相册和系统框架都加载新版。同 ID 的模块原位更新。停用模块并重启即回退全部挂载。设置保存后相机下次读取即生效；快门声设置在铃声模式变化或重启相机后生效。

`post-fs-data.sh` 重建资源前，先延迟卸载本模块在 `/odm/etc/` 的配置与资源绑定，再从原厂目录合并资源，支持 KSU 软重启时重复执行。`/odm/lib64` 的库挂载由 Hybrid Mount 与 `post-mount.sh` 管理。

默认关闭：这套总闸在装了自己的灵感构图模块的机器上是多余的（`com.linggan.goutu` 除了补特性表，还接管
`CameraConfig.d` 门禁、挂了 `OplusAIComposition` / `OplusAICompositionHelper` 并接了它自己的云端），两个模块
钩同一个方法只会互相打架。只有在没装那类模块的机器上才值得在 Muse 设置里打开它。
