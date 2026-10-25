# 视频复刻助手(桌面端)

PySide6 桌面应用。目前后端是回放假事件流的演示实现,尚未接入真实 agent。

## 运行与测试

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m hypit_desktop          # 运行
.\.venv\Scripts\python.exe -m unittest discover -s tests   # 测试(无界面)
```

数据(任务库、设置)开发时在 `data\`,打包后在 `%LOCALAPPDATA%\HypitDesktop`。
启动失败或崩溃时,信息写入 `%LOCALAPPDATA%\HypitDesktop\crash.log`。

## 打包(Windows)

| 脚本 | 工具 | 产物 | 状态 |
| --- | --- | --- | --- |
| `build_pyinstaller.ps1` | PyInstaller | `dist\hypit-desktop\hypit-desktop.exe` | **发布用** |
| `build.ps1` | Nuitka(需 VS 的 C++ 工作负载) | `build\run.dist\hypit-desktop.exe` | 已知问题,见下 |

发布时拷贝整个产物文件夹,不能只拷 exe。打包前先关闭正在运行的 exe。

### Nuitka 的已知问题

Nuitka 4.3 + PySide6 6.12 + Python 3.10 的组合下,打包出的 exe 会崩溃(访问冲突,退出码 3):

- 同一窗口里连接第二个 `lambda` 作为信号槽,程序启动即崩溃。
- 任务结束、刷新队列列表时崩溃(崩溃位置会随无关代码漂移,疑似底层内存问题,尚未定位)。

排查过:数据库查询、任务页、跨线程发信号、垃圾回收都不是原因;普通 Python 运行和 PyInstaller 打包均正常。
Nuitka 或 PySide6 升级后,可运行 `build.ps1` 重新验证:启动,新建任务并确认生成,等任务完成,看是否崩溃。

### 编码约定

- 连接 Qt 信号**不要用 `lambda`**,用绑定方法或 `functools.partial`,目标函数末尾加 `*_` 容纳多余的信号参数。
- 向 Qt 信号发 Python 对象、后台线程回主线程,一律走 `Signal`。

## 真实后端(Hypit)

设置 → 生成后端 选 “Hypit 真实生成”,任务会调用本机安装的 Hypit CLI(默认 `D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs`)。
**会扣 HypiHub 积分**:提交前一定会弹出带预估费用的确认卡片,默认后端仍是不花钱的演示回放。

当前是第 1 步:每个任务按 `templates/podcast` 新建一个 Hypit 项目(自动 `npm install` 依赖),固定生成示例视频,界面里的主题、图片等参数暂不生效。流程:
准备项目 → `runtime up` → `pricing` 估价(`hypit_desktop/hypit/estimate.py`)→ 确认 → `build` → 轮询 `status` → `get` 导出成片 → 进作品库。
失败原因由 `hypit_desktop/hypit/failures.py` 翻译成可操作的提示(积分不足、字幕越界、渲染浏览器异常、网络等)。

注意:

- 前提:已装 Hypit、已 `hypit auth login hypihub.default`、已 `hypit programs prepare`(渲染浏览器)。Hypit 联网下载需要 `NODE_USE_ENV_PROXY=1`(设置里勾选“使用系统代理”即可)。
- Hypit 没有隐式缓存:同一个 Run 重新提交会把已付费的请求再付一遍。所以失败/取消后在原任务上“重新运行”时,后端会读取上次 Build 的产物清单,
  把属于付费组件的产物(图片、视频、声音、对齐结果,不含最终成片和本地处理结果)写进一个 `retry-N.svrun`(`build-record` + `satisfy`),
  先 `check` 再 `pricing`:没有付费请求就直接本地合成,否则仍弹确认卡片。复用只在“请求没变”时生效(用参数指纹判断);
  复用失败或上次没留下产物时,按全价重来并明确告知。项目目录里的 `.hypit-desktop.json` 记录每个任务提交过的 Build。
  “再生成一个”(成功后的任务)是新任务、新项目,不复用。
- 开发时可在设置里填“项目目录”和“运行文件”,直接用已有项目(例如指向复用产物的 `reuse.svrun`,不花钱)走通整条流程。

## AI 导演后端(设置 → 生成后端 → “AI 导演 + Hypit 真实生成”)

流程:准备项目(按语言装字体包,复制参考视频和替换图片) → **AI 导演**(Claude Agent SDK + 兼容接口的模型,默认 DeepSeek `deepseek-flash`)
读真实的 Hypit Skill、看参考视频、写 Source/Run 并 `hypit check` → 应用 `pricing` 估价、弹确认卡片 → 应用提交 `build` → 跟踪进度 → 导出成片。

- **花钱的命令只由应用执行**:导演的 `hypit` 是护栏脚本(`hypit_desktop/agent/guard/hypit_guard.mjs`),`build`/`auth`/`download` 等一律拒绝,`transcribe` 最多 3 次。
- **密钥**:放在环境变量里(默认 `DEEPSEEK_API_KEY`,设置里可改名),不会写进任何文件。
- **自动重试**(`agent/agent_backend.py`):遇到 502、连接重置这类临时故障,等一会儿后自动用 `build-record`/`satisfy` 复用已生成的素材重新提交,
  最多 3 次;累计预估超过你确认金额的 1.5 倍时会再弹一次确认卡片。合成阶段的脚本问题(例如字幕越界)会让导演修正后再提交,最多 2 次。
- **重做**:成片页“不满意,重做…”会新建一个任务,沿用原项目和 AI 会话,按你的反馈只改需要改的部分,没动的素材由导演在 Run 里复用。
- **失败后重新运行**:参数没变就沿用上次写好的脚本,并复用已付费素材(不重新创作、不重复付费)。
- 目前真实可用的模型:Seedance 2.5 / 2.0 VIP / 2.0 Fast VIP / 2.0 Mini;分辨率 480p/720p/1080p。其余模型会在开始前给出明确提示。
- 参考视频是链接时需要先在终端运行一次 `hypit download prepare`(要先装 uv);否则请选“本地文件”。
- 不花生成费的联调:`.\.venv\Scripts\python.exe experiments\run_agent_backend.py --reference <视频>`(到确认卡片为止,自动选“取消”)。
