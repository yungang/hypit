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

## AI 导演后端(设置 → 生成方式 → “AI 导演 + 真实生成”)

流程:准备项目(按语言装字体包,复制参考视频和替换图片) → **AI 导演**(Claude Agent SDK + 兼容接口的模型,默认 DeepSeek `deepseek-flash`)
读真实的 Hypit Skill、看参考视频、写 Source/Run 并 `hypit check` → 应用 `pricing` 估价、弹确认卡片 → 应用提交 `build` → 跟踪进度 → 导出成片。

- **花钱的命令只由应用执行**:导演的 `hypit` 是护栏脚本(`hypit_desktop/agent/guard/hypit_guard.mjs`),`build`/`auth`/`download` 等一律拒绝,`transcribe` 最多 3 次。
- **密钥**:在「设置」里填写并点“测试连接”,保存到 **Windows 凭据管理器**(`hypit_desktop/credentials.py`),不写进 settings.json 或项目目录。
  AI 导演(服务商下拉:DeepSeek / 自定义)和火山方舟各一把。没有填写时回退到环境变量 `DEEPSEEK_API_KEY` / `ARK_API_KEY`。
  方舟密钥只交给 Hypit 的生成进程;导演(模型)的环境里只有占位符,导演的命令白名单也拒绝读取任何看起来像密钥的变量。
- **服务商和密钥**(设置页):每个服务商一把密钥,切换服务商时自动填入已保存的密钥(没有就留空),同一个服务商同时做导演和生成时共用一把。
  - AI 导演:DeepSeek(默认,已验证)、Anthropic(原生协议,密钥以 `x-api-key` 发送)、OpenAI、自定义。**OpenAI 暂时只能保存密钥和测试连接**:
    它的接口不是 Anthropic 协议,运行导演需要一个协议转换网关,还没有做;选它开始任务时会在花钱前给出提示。
  - 视频和图片生成:火山方舟(默认,已接入)、OpenAI、Gemini、Grok(Anthropic 不提供图片或视频生成,不在列表里)。**除方舟外都只能保存密钥和测试连接**:
    其余三家需要另写 Hypit 接入包(`providers/`);选它们开始任务会在花钱前被拦下。旧版本保存过的、现在已不存在的服务(如 anthropic)同样会被拦下,不会悄悄换成别的服务。
  - “测试连接”对每家都是只读或不计费的请求(方舟用不完整的任务,OpenAI/Gemini/Grok/Anthropic 列模型),密钥只放请求头,不放网址。
- **生成服务**(设置 → 视频和图片生成):默认**火山方舟**直连(Seedance 视频 + Seedream 文生图,费用直接付给方舟),`hypihub` 保留为旧方案。
  方舟接入包在 `providers/provider-ark`(由 `providers/make_provider_ark.py` 从 `@hypit/provider-tokendance` 生成),只开通并映射了
  Seedance 2.0 Mini 和 Seedream 5.0 flash;要加别的 Seedance 版本,在控制台开通后把模型 ID 填进 `make_provider_ark.py` 和 `agent/services.py`。
- **方舟的限制**:含人脸的图片只能用 Seedream **文生图**(`TextImage`)生成,图生图出的人脸 Seedance 会拒绝;提示词里已经写成硬规则。
  费用按 `hypit/ark_prices.py` 的价目表估算(元),实测误差约 2%;导演被告知单价和“总生成秒数不超过成片的 1.25 倍”的上限。
- **本地语音对齐**(WhisperX)由应用统一管理,所有任务共用一份环境(设置里“本地语音对齐服务”指向包含 `.venv` 的文件夹),
  Hypit 只通过 `serviceCommand` 启动它,避免每个任务重装。
  **给员工机器部署**:在一台已经下载好模型的机器上运行 `.\deploy\build_whisperx_bundle.ps1 -Target C:\HypitDesktop\services\whisperx -NltkData <含 tokenizers\punkt_tab 的文件夹>`,
  它会建好 Python 环境(含解释器)、复制模型和句子数据、生成 `start-whisperx.cmd`,并离线检查所有模型能加载(成品约 3.9 GB,压缩后更小)。
  环境里记录的是绝对路径,所以**必须解压到和构建时相同的路径**。中文和英文对齐都已验证;英文模型文件曾被断线截断(只有 9.9 MB),脚本会拒绝小于 300 MB 的文件。
- **自动重试**(`agent/agent_backend.py`):遇到 502、连接重置这类临时故障,等一会儿后自动用 `build-record`/`satisfy` 复用已生成的素材重新提交,
  最多 3 次;累计预估超过你确认金额的 1.5 倍时会再弹一次确认卡片。合成阶段的脚本问题(例如字幕越界)会让导演修正后再提交,最多 2 次。
- **重做**:成片页“不满意,重做…”会新建一个任务,沿用原项目和 AI 会话,按你的反馈只改需要改的部分,没动的素材由导演在 Run 里复用。
- **失败后重新运行**:参数没变就沿用上次写好的脚本,并复用已付费素材(不重新创作、不重复付费)。
- 目前真实可用的模型:方舟下只有 Seedance 2.0 Mini(480p/720p);HypiHub 下有 2.5 / 2.0 VIP / 2.0 Fast VIP / 2.0 Mini。其余模型会在开始前给出明确提示。
- 参考视频是链接时需要先在终端运行一次 `hypit download prepare`(要先装 uv);否则请选“本地文件”。
- 不花生成费的联调:`.\.venv\Scripts\python.exe experiments\run_agent_backend.py --service ark --whisperx-home <文件夹> --reference <视频>`(到确认卡片为止,自动选“取消”;加 `--go` 才真正生成)。
