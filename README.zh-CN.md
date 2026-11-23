[English](README.md) | **简体中文**

# 文献综述生成器

给出一个题目，它会生成一篇文献综述，其中的参考文献都真实存在、可以核查。整个过程分为八个可以实时查看的阶段：
由你批准综述范围，然后程序检索 OpenAlex 和 arXiv、筛选结果、记录笔记、按主题组织文献、规划提纲、撰写综述并进行检查。
界面和综述都支持英语和简体中文。

它是 [Directed Growing Sheet](https://github.com/unscttp/Directed-Growing-Sheet)（DGS）的示范应用。
DGS 是一个以 JSON 为核心的 AI 智能体工作流引擎。综述可信与否的关键——每个阶段能做什么、什么时候需要你决定、
哪些文献可以被引用——都由 DGS 强制执行，而不是靠提示模型“请遵守”。

- **不会编造参考文献。** 每篇文献都来自真实的检索结果，并在本次综述的文献库中获得一个编号（P1、P2……）。
  模型只能按编号引用；参考文献表由程序根据文献库记录生成，格式可选 APA 第 7 版、GB/T 7714-2015 或 MLA 第 9 版，
  并附 BibTeX 文件。检查功能会标出引用了不存在或未纳入文献的地方。
- **由你批准综述范围。** 检索开始前，你会看到研究问题、纳入排除标准和检索式。可以直接批准，
  也可以写下修改意见退回：模型会修改后再次提交。
- **实时工作流视图。** 显示八个阶段、哪个阶段正在工作、在做什么。当某个阶段运行技能的示例图时，
  这张图会带着自己的节点显示在该阶段下方。
- **带示例图的技能。** 四个 Agent Skills 为各阶段提供指导：文献检索、筛选与信息提取、组织综述、撰写综述。
  每个技能都带有一张针对某类综述的图（英语文学研究、教育学实证研究、快速发展的计算机科学领域、
  使用 GB/T 7714 的中文综述）。
- **双语。** 英语和简体中文界面；综述可以用任一语言撰写；文献可以是任何语言。

## 快速开始

需要 **Python 3.10 或更高版本**（用 `python --version` 检查；在 Windows 上安装时请勾选“Add python.exe to PATH”），
以及所用模型的 **API Key**：Gemini、Claude、GPT 或 DeepSeek。用 Ollama 或 LM Studio 在自己电脑上运行的模型不需要密钥。

```bash
git clone --recursive https://github.com/unscttp/Literature-Review-Generator
cd literature-review-generator
python install.py
```

`install.py` 会把所需的一切安装到独立目录（`.venv`）中，运行测试，并询问使用哪个模型
（默认 Gemini 4 Hydrogen，也可以选择其他模型）。然后启动程序：

```bash
python run.py
```

浏览器会打开 http://127.0.0.1:8765。使用期间请保持终端窗口开启；按 Ctrl+C 停止程序。

**不选模型，先试一试：**

```bash
python run.py --demo
```

演示模式用几条虚构的示例记录运行一篇预设脚本的综述：不使用 AI，不需要密钥，也不联网。
它会展示每个阶段、范围审批和一张技能图。

如果你下载的是 ZIP 而不是用 git 克隆，`install.py` 会自动获取 DGS。

## 撰写一篇综述

1. **新建综述。** 描述题目，选择综述语言、引用格式、综述类型（叙述性、范围综述或系统性风格）、
   发表年份、计划纳入的文献数量和文献来源。
2. **批准范围。** 大约一分钟后会出现综述范围。可以批准，也可以写明需要修改的地方后退回。
3. **查看进度。** “工作流”标签页显示各个阶段，点击阶段可以查看它的结果。“文献库”列出检索到的所有文献，
   包括筛选决定及理由、笔记和主题。“运行记录”列出每一次工具调用。
4. **阅读与下载。** “综述正文”显示正在撰写的综述以及引用检查的结果。可以下载 Markdown 格式的正文和
   BibTeX 格式的参考文献。

**需要多少次模型调用？** 每个阶段都有步数上限，并随计划纳入的文献数量增加
（`config/workflow.json` 中的 `max_steps` 加上 `config/settings.json` 中的 `steps_per_paper`）。
八个阶段最多约 130 次调用（5 篇文献）、185 次（25 篇）或 330 次（80 篇）；阶段每运行一张技能图，最多再增加 120 次。
新建综述的表单会显示你这篇综述的数字。范围很广的领域会用掉大部分额度：加上技能图，大型综述可能接近 1000 次调用。
请留意服务商的速率限制和费用；如果阶段的步数不够用，可以在上述两个文件中调高上限。
运行在后台进行，关闭浏览器标签页也不影响。如果运行期间程序被停止，打开这篇综述并点击**继续**即可：
已完成的步骤不会重复执行。

## 工作原理

工作流定义在 `config/workflow.json` 中：八个依次相连的 LLM 节点。每个节点都有自己的指令、步数上限和
**权限集（allowance）**，即它可以调用的工具的完整清单（`config/allowances/`）。DGS 会按权限集检查每一次工具调用。

| # | 阶段 | 作用 | 可用的工具 |
| --- | --- | --- | --- |
| 1 | 确定范围 | 研究问题、标准、检索式；由你批准 | `scope.submit`，读取检索技能 |
| 2 | 检索 | 检索 OpenAlex 和 arXiv；结果进入文献库 | `lit.search_openalex`、`lit.search_arxiv`、`library.list/get`，文献检索技能及其示例图 |
| 3 | 筛选 | 逐篇决定纳入或排除，并给出理由 | `library.list/get/decide/note`，筛选与提取技能及其示例图 |
| 4 | 提取 | 记录方法、数据、发现与局限 | `library.list/get/note/decide` |
| 5 | 组织 | 主题、比较、研究空白 | `library.list/get/tag`，组织综述技能及其示例图 |
| 6 | 提纲 | 各章节及其引用的文献 | `library.list/get`、`review.set_outline` |
| 7 | 撰写 | 撰写各章节，按文献库编号引用 | `library.list/get`、`review.write_section/read`，撰写综述技能及其示例图 |
| 8 | 审校 | 修正检查发现的问题，撰写摘要 | `review.check/read/write_section/delete_section` |

各阶段通过任务数据（`/stages/<id>`）传递结果；文献库、提纲和章节是本次运行目录（`data/runs/<id>/`）中的文件。
只有第 2 阶段可以访问网络，而且只能访问学术检索接口。任何阶段都不能读写其他文件。

**范围审批**是 `scope.submit` 工具中的一个 DGS 人工检查，标记为 `"on_reject": "continue"`：
你退回范围时，工具把你的意见返回给模型，而不是结束运行。如果模型没有提交范围就直接给出回答，
运行后钩子（post-run hook）会请你批准这个回答；拒绝则结束运行。

**引用**由 `lrg/references.py` 在每次显示正文时根据文献库记录生成，因此正文和参考文献始终一致。
作者、年份和出处都来自 OpenAlex 和 arXiv，而不是模型。

**技能**是 `skills/` 中的 Agent Skills：`SKILL.md` 中是指导说明，`references/` 中的文件由各阶段通过
`skill.<名称>.read` 读取。每个技能的 `graphs/` 中有一张示例图，DGS 会校验它（使用场景说明带有哈希值），
阶段可以用 `skill.<名称>.run_graph` 运行它：

| 技能 | 示例图 | 适用于 |
| --- | --- | --- |
| literature-search | `english-literature` | 英语文学研究：针对作者与作品、批评方法、历史背景与学术争论的检索式；两个并行的检索节点；覆盖面检查 |
| screening-extraction | `empirical-education` | 教育学实证研究：带排除代码的 PICOS 标准、标题与摘要筛选、不确定文献的判定、结构化信息提取 |
| review-organization | `fast-moving-cs` | 以月为单位快速发展的计算机科学领域：时间线与里程碑、方法类别、比较、开放问题与预印本的注意事项 |
| review-writing | `chinese-gbt7714` | 使用 GB/T 7714 的简体中文综述：术语表、中文学术语体初稿、修改润色 |

示例图中节点的权限集比运行它的阶段更窄（如果子图的权限超出父节点，DGS 会拒绝运行）。
每次运行后，DGS 会在 `data/skills/<技能>/graphs/<id>.meta.json` 中记录运行结果和所用模型；
之后如果运行条件不同，阶段会得到相应提示。

**工作流视图**通过 DGS 的运行观察器（run observer）跟踪进度，它会报告每一次节点执行，包括技能图运行期间的节点。

用到的其他 DGS 功能：模型调用超时或触发速率限制时自动重试；阶段达到步数上限时给出回答而不是直接失败；
动作日志（action journal）让中断的运行可以继续，而不重复已完成的工具调用。

## 配置

| 文件 | 内容 |
| --- | --- |
| `config/workflow.json` | 各阶段：指令、步数上限、权限集 |
| `config/allowances/*.json` | 每个阶段（以及每个技能图节点）可以做什么 |
| `config/rules.md` | 所有阶段都会收到的规则：不得编造文献、按编号引用、使用的语言 |
| `config/settings.json` | 端口、DGS 引擎设置、新建综述表单的默认值 |
| `skills/` | 技能及其示例图（修改示例图后请运行 `python scripts/skill_graphs.py`） |
| `.lrg/config.json` | 你选择的模型和密钥（由设置程序创建，只保存在本机） |
| `.lrg/settings.json` | 你的 OpenAlex 密钥（在程序的“设置”中填写） |
| `data/` | 你的综述和已安装的技能 |

更换模型：`python run.py --setup`。环境变量 `DGS_API_KEY`、`DGS_MODEL` 和 `DGS_BASE_URL`
优先于已保存的模型设置，`LRG_OPENALEX_API_KEY` 优先于已保存的 OpenAlex 密钥。

**OpenAlex** 不需要密钥也能使用，但所有无密钥用户共享每日额度。在 [openalex.org](https://openalex.org)
免费申请的密钥有独立额度；请在“设置”中填写。**arXiv** 不需要密钥；按照 arXiv 的要求，程序每两次请求之间间隔三秒。

## 局限

- 各阶段阅读的是标题、摘要和元数据，而不是全文。摘要没有提到的内容，笔记中会写“未报告”；
  但基于摘要的综述会遗漏只有全文才有的信息。
- 筛选和综合由 AI 模型完成。请把生成的综述视为来源可靠的初稿：在使用之前，请核查纳入的文献以及对它们的表述。
- OpenAlex 和 arXiv 覆盖面很广，但并不完整（部分出版社、许多非英语期刊、灰色文献）。方法部分会如实说明检索了什么。
- 元数据可能不完整（缺少期号、大小写不规范等），提交前请检查格式化后的参考文献。

## 遇到问题时

| 提示 | 处理方法 |
| --- | --- |
| “还没有选择模型” | 运行 `python run.py --setup`。 |
| “Cannot use port 8765” | 端口被其他程序占用：`python run.py --port 8766`。 |
| 阶段失败并提示 HTTP 401 或 403 | 密钥未被接受：运行 `python run.py --setup`。 |
| 模型超时或 HTTP 429 | 服务繁忙；DGS 会自动重试。如果运行已停止，请点击**继续**。 |
| “OpenAlex refused the request: ... budget” | 在“设置”中填写免费的 OpenAlex 密钥，或等到第二天。 |
| “Directed Growing Sheet is missing” | 运行 `python install.py`。 |

## 开发者

```bash
python -m unittest discover -s tests -t .
```

测试使用预设脚本的演示模型和模拟的文献来源运行完整的综述，因此不需要密钥，也不需要联网。代码结构：

| 路径 | 内容 |
| --- | --- |
| `lrg/pipeline.py` | 运行管理：每篇综述是一个 DGS 任务，在后台线程中运行 |
| `lrg/tools.py` | 综述所用的工具，每次运行一个 DGS 工具模块 |
| `lrg/library.py`、`lrg/report.py`、`lrg/references.py` | 文献库、章节与检查、引用格式 |
| `lrg/sources.py` | OpenAlex 和 arXiv（仅使用标准库） |
| `lrg/graph_view.py`、`lrg/live.py` | 工作流视图背后的数据 |
| `lrg/server.py` | 本地 Web 服务器（仅使用标准库）及其 JSON 接口 |
| `lrg/demo.py` | 演示用的脚本模型 |
| `web/` | 界面：纯 HTML、CSS 和 JavaScript；界面文字在 `web/i18n/` 中 |
| `third_party/dgs` | Directed Growing Sheet（git 子模块） |

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证。
