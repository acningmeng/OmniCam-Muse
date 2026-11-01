# X8U 重做：从干净基线重排适配层

分支：`x8u-rebuild`，基线 `03f199c`（上游最后一次提交）。
`main` 上 11 个提交保留不动，只作历史参考；本分支重新组织，不继承其结论。

---

## 1. 为什么要重做

`main` 那条线上，设备最终出现「照片/POP/理光全都不出片」，而**同一台机器把模块整体停用后立刻恢复正常**
（实测：停用后 `IMG20261101224754.heic` 2,789,160 B 正常落盘）。这说明问题在我们自己的层，不在系统。

排查过程中我把状态搅浑了三次，这些教训直接决定本分支的结构：

| 事故 | 原因 | 本分支的对策 |
| --- | --- | --- |
| 相机卡死/取景黑 | 运行期 `mount --bind` 换 `/odm/etc/camera/config/*`，provider 早就持有旧 inode | 配置只允许**开机时**绑；运行期一律不改，改就 soft-reboot |
| LSPosed 全部失效 | 只拉主库（4 KB）改 `modules_config.db`，丢掉 WAL 里的 schema，把注册表写空 | 不手改 LSPosed 数据库；开关与作用域只通过 LSPosed 管理器 |
| POP 黑屏 | `umount` 掉 `basictone` / `meishe_lut` 做对照，POP 的胶片色调表就在里面 | 对照实验不得动这两个合并目录；测试脚本只读 |
| 手机卡死 | `killall lspd` 拖死 zygote/system_server | 永不 kill lspd；要停 hook 用模块自身开关 + 重启相机进程 |
| 临时 root 丢失 | 该 soft-reboot 的场景用了 `adb reboot` | 一律 `ksud soft-reboot`；只有内核/分区级改动才 `reboot` |

## 2. 分层与开关（默认全关，逐层打开）

本分支不再「一次全开」，改成四层，每层有独立开关与验收标准。**默认只开 L0**。

| 层 | 内容 | 开关（`/data/adb/modules/<id>/` 下的标记） | 验收 |
| --- | --- | --- | --- |
| L0 | 设备闸门、LUT/资源 staging、日志 | 无（总是开） | `selftest.sh gate` |
| L1 | 符号层（dex 定位 + Java hook 安装） | `enable_hooks` | `selftest.sh hooks` |
| L2 | 配置层：`camera_unit_config` + `camera_unit_feature_config.protobuf` | `enable_config_binds` | `selftest.sh shoot photo` |
| L3 | APS 表（`oplus_camera_algo_switch_config`，POP/理光快门前提） | `enable_algo_switch` | `selftest.sh shoot retro` |
| L4 | `oplus_camera_config` 增补标签（调色板/GR 元数据） | `enable_occ_extras` | `selftest.sh shoot gr` |

规则：

1. 上一层验收不过，不准开下一层。
2. 任何一层出问题，删掉对应标记文件 + `ksud soft-reboot` 就回到上一层，不需要改代码。
3. 每层都有自己的 `bind.log` 段落（`log "layer L2 ..."`），出问题先看日志再动设备。

## 3. 从两份参考包里取什么

### r31（`OmniCam-Muse-4.4.4-r31-KSU`）

拿：
- **APS 表的做法**——`oplus_camera_algo_switch_config` 是「哪些模式有 APS 预览结果」的唯一登记处，
  POP 是 X8U 原厂唯一没登记的模式，`BaseMode.m8()` 因此拒绝每一次快门。这一条我们用
  `tools/build_x8u_algo_switch_config.py` 复现（在本机原厂表上插 `retroCamera` 的 capture/preview 两块）。
- **protobuf 的坑**——field2/field3 是 field1 字符串池的下标，X9U 池 319 条、X8U 296 条，从 index 50 起分叉；
  直接搬表会 `IndexOutOfBoundsException: Index 314 out of bounds for length 296`。所以 feature 表要么整份绑定
  且接受字符串池差异（我们走这条），要么按字符串内容重映射重建（他们那条，复杂度高，暂不做）。
- **`x8u-fix-pop.sh` 的 pair-list 教训**——`camera_unit_config` 必须是 `{k: v}` 对象，写成 `[[k,v],…]`
  会让 `JsonParser.parseUsecaseInfo()` 抛异常并返回半张表，后面的 `retro_camera_case` 全丢。

不拿：
- 他们的 native 层（`libextensionlayer.so`、`caflogicaldriver.so`、`oplus_eis_camera.vcfg`）——我们没验证过，
  且 `x8u-fix-pop.sh` 自己也把它们放在 `enable_native_isz` 后面默认关。

### test75（`MUSE-X8U-V2-test75-KSU`）

拿：
- **`device.sh` 闸门思路**（机型 + 固件 + 相机版本）——我们已有 `module/device.sh`，本分支补上相机版本比对。
- **`mount-state.sh` 记录式卸载**——避免按路径前缀暴力 umount 把别人的挂载也拆掉。
- **POP 走单帧兼容路径**的说明——他们明确写「避开 HybridRAW/TurboHDR 低曝光黑帧」「关闭快速 JPEG 提前显示」，
  这正是我们相机在 POP 下偶发黑帧/半帧的方向，留作 L3 之后的调优项。

不拿：
- 他们的 `oplus_camera_config`（82,175 B / 596 个 tag 那一套）——我们用「本机原厂表 + 11 条标签」的增量做法，
  且这一层默认关（L4）。
- 他们的 APK（30 MB，功能集与我们的符号层不兼容，混用只会两边都不对）。

## 4. 保留 / 重写的清单

保留（已验证过、与本机无关的部分）：
- `tools/symbols/port_x8u.py` + `app/src/main/assets/symbols.json` 的 4 条改动（`Zoom.labelBitmap=J6`、
  `EffectItemView=if.s0$c`、`Personalized.style=i1`、`Personalized.labels=X0`）。
- `app/src/main/java/local/jiege/hook/common/FeatureModeCompat.java`（feature 表里缺某个 mode 的
  operation 表时补空 Map，避免 `CameraConfigHelper.getFeatureOperationMode` NPE）。
- `module/device.sh` + `module/mount-state.sh`。
- `tools/profiles/*`（档案生成 / payload 合成 / 包校验）与 `tools/build_x8u_algo_switch_config.py`。

重写：
- `module/post-fs-data.sh`：改成第 2 节的四层结构，默认只跑 L0+L1；L2 及以上要标记文件。
- `tools/build_x8u_oplus_camera_config.py`：改为**只产出候选清单**，不直接替换 payload（L4 默认关）。
- 所有「运行期 bind」的验证脚本：删掉，统一成 `tools/x8u_selftest.sh`（只读检测 + 需要时提示重启）。

## 5. 灵感构图（AI-01/02）的落地方式

结论先写死：**不碰第三方云，不冒充 OPPO 服务**，走本机启发式。

链路（已从相机 dex 里确认）：
`com.oplus.camera.feature.ai_composition` → `CompositionViewDelegate` → `OplusAICompositionHelper`
→ aiunit `AIConnector(Context, FrameDetector, actionId)` → `FrameDetector.process(FramePackage)`。

我们只做 `FrameDetector` 的实现：

```
com.oplus.aiunit.core.base.FrameDetector (abstract)
  ├─ createInputSlot()  -> com.oplus.aiunit.core.base.j   // j(Bitmap, boolean): int, m(Bitmap): void
  ├─ createOutputSlot() -> com.oplus.aiunit.core.base.k   // j(FrameUnit): void
  ├─ preProcess(j, k, FramePackage)
  └─ postProcess(...)
```

实现步骤：
1. `androidx`/反射两条路都试：优先反射构造 `FrameUnit`（字段名随版本变化，先 dump 再写死到档案里）。
2. 取帧：`input.put(bitmap, true)`，缩放到 640 长边，灰度 + Sobel 求显著边缘。
3. 规则：
   - 三分法：把画面按 3×3 切，算边缘能量加权质心，偏离最近三分点 > 8% 就给「向左/右移动一点」。
   - 水平线：Hough 轻量版（按行累加梯度），地平线倾斜 > 3° 给「保持水平」。
   - 主体占框：连通域最大块面积占比 < 12% 给「靠近一点」，> 65% 给「退后一点」。
4. 输出：`FrameUnit` 里塞 score(0–100) + 1–3 条 tip + 建议框（RectF 归一化坐标）。
5. 节流：每秒最多 2 次，`postProcess` 里做，避免预览掉帧。

验收：`dumpsys` 里 `AICompositionEnterButton` 状态不再是 `G`，取景出现建议卡，且**不联网**也能出结果。

## 6. 落地顺序

1. 本分支先把 L0/L1 做干净：`device.sh` 相机版本比对、`selftest.sh` 五条只读检查、README 改写。
2. L2：把 `camera_unit_config` / `protobuf` 做成「开机绑 + 默认关」，配 `selftest.sh shoot photo`。
3. L3：APS 表进默认关，单独验收 POP/理光。
4. L4：`oplus_camera_config` 只做候选清单。
5. 构图：独立于 L0–L4 的开关 `enable_composition`，即使前四层全关也能单独开。
6. 全部在真机上逐层验收通过后，再考虑把 `main` 的历史提交处理掉（reset 或 revert），本分支合并回 `main`。
