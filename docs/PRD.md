# Path Pilot 产品需求文档（PRD）

> 产品名称：Path Pilot
>
> 文档版本：1.0
>
> 状态：Draft for product alignment
>
> 基线日期：2026-08-07
>
> 目标读者：产品、设计、前端、后端、AI/RAG、评测与项目评审者

---

## 1. 产品摘要

Path Pilot 是一个面向 NYU School of Professional Studies（SPS）研究生的独立学业规划工具。学生通过对话描述目标、粘贴注册错误或导入非官方成绩单，系统读取学生主动提供的课程记录，结合公开发布的项目要求、课程目录和学校政策，生成有来源、可审阅、可修改的注册准备方案。

Path Pilot 不连接 Albert，不读取官方学生记录，不代表 NYU，也不执行注册、清除 hold、批准例外或修改官方成绩。它的产品承诺是：

> 告诉 Path Pilot 你修过什么、正在修什么以及想完成什么；Path Pilot 会说明公开规则如何适用于你，并把不能确认的部分明确留给你或学校工作人员决定。

Path Pilot 的差异化不在于“能聊天”，而在于以下闭环：

1. Agent 理解学生任务并调用受控工具；
2. 确定性引擎计算 degree、mission、sequence 和 decoder 结果；
3. RAG 提供适用政策证据，而不是替代业务计算；
4. 结果以内嵌交互卡片呈现；
5. Agent 只能提议，学生完成所有实质决定；
6. 每次回答可追溯、可回放、可评测。

---

## 2. 背景与问题

### 2.1 用户问题

学生完成一次可靠的注册规划，通常需要在多个信息源之间切换：

- Albert 中的个人记录、holds、注册时间和课程状态；
- Bulletin 中的项目要求、先修课和学术政策；
- Registrar、Bursar、Financial Aid 和 SPS 页面中的流程与日期；
- Advisor 对例外、替代课程和个人情况的判断。

主要困难不是“找不到一个页面”，而是：

- 不知道哪条政策适用于自己的 school、level、program 和 catalog year；
- 不知道已修课程如何映射到项目要求；
- 无法同时考虑先修顺序、开课学期、学分上限和毕业期限；
- 注册错误信息简短、含糊，学生不知道原因或该联系谁；
- AI 回答往往流畅但无法证明来源、时效和适用范围；
- 信息不足时，系统容易把“看不到”误说成“没有问题”。

### 2.2 产品机会

Path Pilot 将分散的查找和计算任务收敛为一个可审阅工作流：

```text
学生目标
→ 读取自报记录
→ 检索适用政策
→ 调用确定性规划工具
→ 生成方案卡片
→ 学生确认或修改
→ 形成可交给 advisor 的 handoff
```

产品应减少学生在多个页面间手工比对的成本，但不能制造“已替你完成注册”或“已验证官方记录”的错觉。

---

## 3. 产品愿景与原则

### 3.1 愿景

成为 SPS 学生在注册前最可信的独立准备层：先帮助学生理解自己的记录和公开规则，再把真正需要 Albert 或学校工作人员确认的问题清楚地交接出去。

### 3.2 产品原则

1. **Agent-first，不是 chat-only**  
   对话是任务入口；表格、课程候选、证据、学期序列和审批操作必须以适合任务的 UI 呈现。

2. **确定性计算优先于模型推理**  
   学位要求、先修顺序、mission 状态和错误分类由可测试代码计算；模型负责理解、编排和解释。

3. **事实必须有来源**  
   每个事实性结论必须引用本轮工具实际返回的 source ID；模型不得凭训练数据补全校内规则。

4. **适用性先于相似性**  
   权限、学校、学位层级、项目、学年和有效期应在检索或重排阶段处理，不能把错误学院的相似政策交给模型自行判断。

5. **不确定性必须可见**  
   `ambiguous`、`needs_review`、`unverifiable` 和 `unreadable` 是正式产品状态，不得被压成二元成功/失败。

6. **Agent 提议，学生决定**  
   Agent 可以创建空 mission 容器和未确认建议，但不能确认课程、接受风险或代表学生完成正式动作。

7. **重新读取真实状态**  
   持久状态由事实重新计算；卡片动作完成后必须使用服务器返回或重新读取的权威状态更新界面。

8. **明确能力边界**  
   没有 Albert 集成就是“无访问能力”，不是“查询结果为空”。

9. **Eval 是产品功能**  
   功能没有对应的准确性、安全性或轨迹评测，不视为完成。

---

## 4. 目标与非目标

### 4.1 当前产品目标

- 让学生从全屏对话进入，而不是先猜应该打开哪个工具页；
- 在一轮中完成“查记录 → 查 mission → 提议课程 → 计算 sequence → 给出下一步”；
- 让工具结果成为可交互卡片，并在卡片中完成真实确认动作；
- 允许学生通过手动输入或成绩单导入建立自报课程记录；
- 对每个高风险结论显示来源、适用范围、时效和限制；
- 在信息不足、冲突、过期或越权时安全降级或升级给人工；
- 用可重复评测证明检索、权限、引用、规划和解析边界仍然成立。

### 4.2 下一阶段目标

- 提升政策语料的权威性、覆盖率、版本管理和适用性过滤；
- 将基于 `tool_trace` 推断卡片升级为正式 Artifact Contract；
- 增加后端真实工具事件的过程可见性；
- 完成 invite-only beta 所需的隐私、限流、成本和可观测性；
- 为更多 SPS graduate programs 建立可验证的 requirements/course graph。

### 4.3 非目标

- 不替代 Albert 或任何 NYU 官方系统；
- 不承诺课程有座位、学生已满足所有官方条件或一定能按时毕业；
- 不自动注册、退课、清除 hold、修改成绩或提交正式申请；
- 不给出法律、医疗、移民或心理健康建议；
- 不将模型生成的课程关系写入确定性规则库；
- 不以抓取页面数量代替语料完整性；
- 不在未经学生确认的情况下把 OCR/解析结果写入 profile；
- 不在当前阶段支持 NYU 全部学院和全部项目的高置信 degree audit。

---

## 5. 用户与核心任务

### 5.1 主要用户：SPS Graduate Student

核心问题：

> 我现在还差什么、下学期应该怎么选、有哪些风险需要在 Albert 或 advisor 那里确认？

主要任务：

- 建立或更新课程记录；
- 理解 degree progress；
- 规划下一学期和后续学期；
- 解读注册失败信息；
- 准备 registration mission；
- 把未解决问题整理给 advisor。

### 5.2 唯一用户：学生（2026-08-08 起）

原来还有三类次要用户，各有自己的视图：Advisor 的 triage queue、Registrar 的 capacity
pressure、Finance 的 case list。这三个界面已于 2026-08-08 删除，理由写在这里以免日后被
当成疏漏：它们本来就属于 demo/portfolio scope，从来没有真实的 staff workflow 在后面
接住；而每次改动学生端，都要多付三份维护成本。一个把一件事做透的作品集项目，胜过四件事
各做一半。

被删掉的是产品界面，不是权限模型：

- `advisor` 作为 `User` 上的角色保留，但**不能登录**（seed 中 `password_hash` 为空）。
  它的两个用途都不是界面：学生记录上写着自己的 advisor 是谁，而 handoff 邮件正是写给
  这个人的；检索的 audience 过滤需要至少两个受众，否则 leak probe 就不再是测试。
- 最小权限原则现在只剩一句话：**调用者只能读到自己的记录**。这句话由两个可登录的学生
  账号双向验证，比原来单向的 advisor 越权检查更强。
- Registrar / Finance 角色已从 `UserRole` 枚举中删除。

---

## 6. 产品范围与当前基线

| 能力 | 当前状态 | 产品判断 |
|---|---|---|
| Agent-first 学生首页 | 已实现 | Chat 是默认入口，旧工具页保留为次级入口 |
| 结构化工具卡片 | 已实现基础版 | 当前依据 tool trace 重新读取权威 endpoint |
| Mission 卡片内确认/拒绝 | 已实现 | 与完整 Mission 页面调用相同学生接口 |
| 一轮注册准备 | 已实现 | Agent 可读取状态、创建空 mission、提议、sequence |
| Agent 创建 mission | 已批准并实现 | 仅创建空容器，不构成课程决定 |
| 轻量多轮历史 | 已实现 | 最近 6 条文本消息；不回放旧工具结果 |
| Sequence solver | 已实现 | 先修、开课模式、学分上限、方向和 deadline 联合求解 |
| Decoder | 已实现 | 规则分类，保留 ambiguous/unrecognized |
| Transcript PDF intake | 已实现 | 三态 review 后确认写入 |
| Transcript photo OCR | 已实现受限版 | 所有 OCR 行强制 needs_review |
| RAG、引用和审计 | 已实现 | 角色预过滤、来源校验、回放日志、eval |
| Artifact Contract | 未正式实现 | 仍需从 tool trace 推断并二次获取卡片数据 |
| 后端真实进度事件 | 未实现 | 当前只有前端计时等待文案 |
| 持久 conversation/thread | 未实现 | 当前历史主要在客户端本轮会话内 |
| 多项目高置信规划 | 未实现 | 当前高置信范围为一个已编码项目 |
| Invite-only beta hardening | 未完成 | 需要限流、成本、隐私和部署验收 |
| Advisor / Registrar / Finance 视图 | 已删除（2026-08-08） | 产品收敛为纯学生端，权限模型与 leak probe 保留 |

---

## 7. 核心用户旅程

### 7.1 新用户：从零建立可规划记录

1. 学生登录；
2. 系统检测 profile 为空，显示确定性欢迎语；
3. 学生选择上传成绩单、手动输入，或先解读注册错误；
4. 上传后看到逐行 review：`matched`、`needs_review`、`unreadable`；
5. 只有学生勾选并确认的课程写入自报 profile；
6. 系统重新计算 degree progress，并提供“规划下学期”入口。

成功条件：学生理解导入结果不是官方记录，并能发现、修正或跳过不确定行。

### 7.2 一轮规划下学期

1. 学生说“帮我规划下学期”；
2. Agent 读取 profile、degree plan 和 mission；
3. 没有 mission 时，Agent 在 term 明确或使用可披露默认值后创建空容器；
4. Agent 提出未确认候选课程；
5. Sequence solver 计算剩余课程顺序；
6. UI 展示文本总结、Mission 候选卡、Sequence 卡和 Albert 检查项；
7. 学生在卡片内逐门确认或拒绝；
8. 卡片使用服务器重新计算后的 mission 状态更新。

成功条件：一轮输出是可整体审阅的方案，而不是要求学生连续回答多个机械问题。

### 7.3 解读注册错误

1. 学生粘贴 Albert 错误原文；
2. Decoder 提取 error code、课程号、hold code 和 term；
3. 规则表返回 `identified`、`ambiguous` 或 `unrecognized`；
4. UI 高亮触发判断的原文证据；
5. 若 ambiguous，展示多个候选原因和区分问题；
6. Policy retrieval 仅为被识别原因寻找支持材料；
7. 若语料没有覆盖，明确说明没有政策来源，而不是引用近邻页面。

成功条件：系统不把含糊 hold 默认解释为 financial hold，也不把未识别信息猜成某个原因。

### 7.4 继续上一轮计划

1. 学生说“把那门选修课去掉”；
2. 最近文本历史帮助解析指代；
3. Agent 必须重新读取当前 mission/profile；
4. 如果指代仍不唯一，要求学生明确课程；
5. 实质动作仍由学生在卡片上确认，或调用明确授权的学生 endpoint。

成功条件：旧工具快照不会因为被放进 history 而被重新当作当前事实。

---

## 8. 功能需求

### FR-1 身份与入口

**优先级：P0**

- `/` 必须是正式学生登录入口；`/demo` 必须与真实账户分离；
- 登录身份、角色和数据主体只能来自服务器 session；
- 学生登录后默认进入 Chat；
- Mission、Sequence、Decoder、Planner 和 Intake 作为次级工具入口保留；
- 非学生账号（仅剩 advisor 记录）无法登录；即使持有旧 session，也只会看到一句说明和登出按钮。

验收：客户端无法通过提交任意 role 或 student ID 扩大权限。

### FR-2 对话首页

**优先级：P0**

- 欢迎语由 profile 和 mission 状态确定性生成，不调用模型；
- 初始建议必须与当前状态相关；
- 输入框在桌面与移动端保持可达，但不得遮挡最后一条消息或卡片操作；
- 每条回答必须显示 decision 状态、降级信息和来源入口；
- 正在运行时必须显示可访问的 `role=status`；
- 错误后保留用户问题并允许重试。

### FR-3 Agent 编排

**优先级：P0**

- Agent 每轮最多运行预设迭代次数；
- 结束必须调用结构化 `submit_answer`；
- 独立工具查询应尽量同轮并行发起；
- Policy search 必须有预算，耗尽后停止无效改写；
- 本轮历史最多携带最近 6 条用户/助手文本；
- 旧工具调用和工具结果不得作为历史重放；
- 每个事实仍必须由本轮工具重新建立；
- 模型故障必须产生可理解的降级结果，不能直接返回裸 500。

### FR-4 Artifact 与富卡片

**优先级：P0（基础版已实现；正式协议待完成）**

系统至少支持：

- `mission_candidates`；
- `mission_state`；
- `course_sequence`；
- `decoder_result`；
- `proposal_bundle`；
- `transcript_review`；
- `source_evidence`。

卡片要求：

- 显示产生时间、基础状态和关键 caveat；
- 操作按钮调用真实学生 endpoint；
- 操作期间只锁定当前卡片；
- 成功后使用服务器权威状态替换本地状态；
- stale、already-decided、permission denied 和 network failure 必须有恢复路径；
- 完整工具页只作为深入查看入口，不能成为完成核心动作的必要跳转。

### FR-5 Registration Mission

**优先级：P0**

- Mission 是某个 term 的可恢复注册准备任务；
- Mission 状态由 profile、候选课、确认、风险接受和 handoff 事实实时推导；
- 不得存储第二套可漂移的 status；
- Agent 可以创建空 mission，并记录 `created_by`；
- Agent 只能创建 `proposed` candidate；
- 只有学生接口可以 confirm、decline、remove、accept risk 和完成 handoff；
- 一个 proposal 不得推进 mission，也不得破坏已经完成的 mission；
- Mission 完成只表示准备流程结束，不表示课程有座位或注册成功。

### FR-6 Term Sequence

**优先级：P0**

- 输入包括自报课程、起始 term、可选 deadline、每学期学分上限；
- 同时处理先修关系、典型开课学期、方向完整性和毕业期限；
- 目标优先最早完成，其次减少不确定开课假设；
- 无解时必须通过约束放松实验说明 binding constraints；
- 每个依赖未知开课信息的 placement 必须单独标记；
- 不得把“bulletin 没写”解释为“一定开课”；
- 不能 sequence 的开放 elective credit 必须保留为显式 placeholder。

### FR-7 Registration Error Decoder

**优先级：P0**

- 分类必须由规则表计算，不由模型自由判断；
- 必须保留 identified、ambiguous、unrecognized 三态；
- 证据必须来自学生粘贴文本中的实际 span；
- ambiguous 时不得突出一个候选为默认答案；
- 只有实际提及对应原因的政策 passage 才能成为支持来源；
- 未覆盖原因必须明确标注 no policy source；
- **区分两种「无来源」**：一种是语料尚未抓到，属于可补齐的缺口；另一种是学校根本没有、
  也不会有这条规则，属于产品范围边界。`time_conflict` 和 `reserved_seat_restriction`
  属于后者——课程时间重叠是排课的机械结果，保留座位属于排课数据，两者都只有 SIS 能回答，
  而不接入 SIS 是本产品的既定前提。对这两类，「识别原因 + 说明无可引用规则」就是完成态，
  不是待办；
- Follow-up answer 与原文一起重新分类，不维持隐藏 decoder session state。

### FR-8 Transcript Intake

**优先级：P0**

- 仅允许学生上传；
- 限制文件类型和大小；
- 优先读取 PDF 文本层；
- 支持 PDF 和学生常见的图片上传；
- 图片发送到外部 OCR/vision provider 前必须预先披露；
- 文件字节不得持久化；
- 解析输出必须为 `matched`、`needs_review`、`unreadable`；
- OCR 产生的所有行强制为 `needs_review`，不得批量自动确认；
- 只有 review 后单独确认的行才能写入 profile；
- 写入前重新校验 course code、state、term 和 grade；
- 真实成绩单不得进入仓库、日志或测试 fixture。

### FR-9 Profile 与 Degree Planning

**优先级：P0**

- 学生可维护 completed、in_progress 和 planned 课程；
- Profile 是自报数据，所有使用位置必须维持这一表述；
- Degree verdict 来自确定性 requirement engine；
- Demo course/program 与真实 catalog 数据严格隔离；
- 未编码 program 不得返回貌似完整的 degree audit；
- 更改 profile 后，mission、planner 和 sequence 必须在读取时重新计算。

### FR-10 RAG、来源与时效

**优先级：P0**

- 仅公开政策、课程和项目资料进入向量/全文检索库；
- 学生个人记录不得进入共享 embedding corpus；
- 角色过滤必须发生在候选检索前；
- 检索必须支持 school、level、program、catalog year、authority 和 validity metadata；
- 生产查询默认只允许 university-wide、SPS 和被明确请求的外部学院来源；
- Comparison/peer-school 文档应进入 conditional 或 eval scope，不应仅靠软 boost 避免误用；
- Embedding 故障时可以 keyword fallback，但必须保持相同权限边界并显示降级；
- 每个来源必须记录 canonical URL、fetch time、content hash 和有效状态；
- 冲突或无法确定适用版本时不得静默选一条。

### FR-11 来源呈现

**优先级：P0**

每个 source 应能向 UI 提供：

- 标题；
- section/breadcrumb；
- canonical URL；
- owning office；
- authority；
- school/program applicability；
- verified/fetched time；
- stale 状态及说明。

前端不得只显示内部 `source_id` 或没有链接的泛化标签。

### FR-12 Escalation 与人工交接

**优先级：P0**

- Demo mode 可以创建真实 demo Case，并返回 case number；
- Live mode 在没有 staff workflow 时不得声称“已提交给 NYU”；
- Live mode 应生成 advisor handoff，并清楚说明由学生自行发送；
- 涉及例外、申诉、官方记录冲突、毕业承诺和无法验证的高风险问题应升级；
- 解释公开流程本身不应因为“话题敏感”而全部升级。

### FR-13 后端过程事件

**优先级：P1**

系统应提供真实的工具事件流：

```text
run.started
tool.started
tool.completed
tool.failed
answer.completed
run.failed
```

- 第一条状态事件应在请求开始后 1 秒内可见；
- 文案来自实际工具类型，不得模拟不存在的步骤；
- 第一阶段不要求 token streaming；
- 连接中断不得导致已完成的学生动作处于未知状态；
- 部署环境必须验证代理层不会缓冲 SSE。

---

## 9. Agent 权限边界

| 动作 | Agent | 学生 | 说明 |
|---|---:|---:|---|
| 搜索公开政策 | 允许 | 间接允许 | 保持角色和适用范围过滤 |
| 读取登录用户自报 profile | 允许 | 允许 | 不接受模型提供的 user/student ID |
| 创建空 mission | 条件允许 | 允许 | term 明确或默认值被披露 |
| 提议 candidate | 允许 | 允许 | 只创建未确认记录 |
| 确认/拒绝 candidate | 禁止 | 允许 | 学生实质决定 |
| 接受风险 | 禁止 | 允许 | 必须逐项确认 |
| 生成 preview/handoff | 允许 | 允许 | Live mode 由学生自行发送 |
| 修改官方记录 | 禁止 | 禁止 | Path Pilot 无官方系统权限 |
| 清除 hold/批准 exception | 禁止 | 禁止 | 必须由 NYU 相关办公室处理 |
| 把成绩单解析结果写入 profile | 禁止自动执行 | Review 后允许 | OCR 行必须逐项检查 |

任何新增写工具必须：

1. 明确说明它写入的事实；
2. 证明不会越过学生决定边界；
3. 加入 write-tool allowlist；
4. 增加“未请求时不得调用”的轨迹评测；
5. 增加身份、所有权和重放测试。

---

## 10. UI 设计契约

### 10.1 屏幕的真实任务

学生首页的工作不是“展示 AI”，而是帮助学生完成一个可检查的学业决定：理解当前状态、查看证据、修改建议，并知道接下来该去 Albert 还是联系 advisor。

### 10.2 信息层级

1. 当前对话和当前任务；
2. 需要学生决定的 artifact；
3. 风险、不确定性和下一步；
4. 来源和时效；
5. 调试/查阅信息。

不能把模型长文本放在所有结构化结果之前形成文字墙。对于一轮规划，方案卡片应紧邻摘要，并把待决定项置于来源折叠区之前。

### 10.3 工作流形态

- 单列、连续的 conversation workspace；
- Artifact 作为消息流中的一等对象；
- 次级工具页用于深度编辑和历史查阅；
- 桌面端允许更宽的 sequence 表格，但不切换为通用 dashboard card grid；
- 移动端保持单列，卡片动作可换行且触控目标不小于可访问标准。

### 10.4 允许的组件

- Message、Composer、Card、Table、Progress、Alert、Details、Button；
- 明确语义的 Badge：`Proposed`、`Confirmed`、`Needs review`、`Assumption`；
- 对证据文本使用 highlight；
- 对 term sequence 使用有顺序的列表或表格；
- 对 proposal bundle 使用分节 review，而不是无差别 card mosaic。

### 10.5 禁止的通用模式

- 与任务无关的 KPI 卡片、活动流或假数据；
- Bento grid 作为默认首页；
- 装饰性渐变、发光、玻璃效果和无语义动画；
- “Overview”“Insights”“Learn more”等可替换到任意产品的标签；
- 没有真实 endpoint 的按钮；
- 仅用颜色表示安全状态；
- 把桌面布局简单压缩成移动端；
- 用“AI confidence”替代证据、状态或可验证限制。

### 10.6 必须覆盖的界面状态

每个核心 surface 必须实现并可测试：

- loading；
- empty；
- partial data；
- success；
- validation error；
- network/server error；
- permission denied；
- stale artifact；
- already acted elsewhere；
- degraded dependency；
- ambiguous/unverifiable；
- mobile overflow；
- keyboard focus 和 screen-reader status。

---

## 11. Artifact Contract（目标协议）

当前前端通过 `tool_trace` 判断需要重新获取哪些卡片。下一版本应将审计轨迹与 UI 协议分离。

建议响应结构：

```json
{
  "answer": "...",
  "artifacts": [
    {
      "id": "artifact_01",
      "type": "mission_candidates",
      "version": 1,
      "status": "awaiting_student",
      "canonical_ref": {
        "resource": "mission",
        "id": 42
      },
      "data": {},
      "actions": [
        {
          "type": "mission_candidate_decision",
          "candidate_id": 108
        }
      ],
      "source_ids": ["mission:42"]
    }
  ],
  "sources": {},
  "tool_trace": []
}
```

约束：

- `tool_trace` 只用于审计和可选调试显示；
- `artifact.type` 必须来自服务端 allowlist；
- 前端不得接受模型生成的任意 URL 或 HTTP method 作为 action；
- `actions` 只是动作描述，真实 endpoint 和权限由前端注册表及服务端决定；
- 对持久资源，客户端操作前可重新获取 canonical state；
- Artifact schema 必须版本化并有契约测试；
- 未知 artifact type 应安全回退为文本，不得导致整条回答无法显示。

---

## 12. RAG 与语料产品要求

### 12.1 当前基线

- 35 个公开来源页面；
- 1,019 个原始 section；
- 当前 `heading` 策略生成 1,248 个活动 chunks；
- 另有 `section` 和 `fixed` 作为 ablation 对照；
- 当前高置信规划范围集中在 SPS Management Analytics；
- 检索支持 vector、hybrid/RRF 和 keyword degradation path。

### 12.2 语料扩充原则

完整性按“核心问题覆盖”衡量，不按页面数量衡量。语料分为：

1. **Normative**：Bulletin、University Policies、正式项目要求；
2. **Official procedure**：Registrar、Albert、Bursar、Financial Aid 操作说明；
3. **Official guidance**：SPS advising、forms、FAQ；
4. **Eval-only**：其他学院近似政策、过期版本和对抗性文档；
5. **Discovery-only**：论坛和学生表达，只用于发现问题及构造 eval，不支持事实回答。

优先补齐：

- University-wide grading、standing、leave、withdrawal、graduation、transfer；
- Registrar/Albert、waitlist、swap、add/drop 和 calendar；
- Bursar、refund、payment dates；
- Financial Aid、SAP、withdrawal impact；
- SPS procedures/forms；
- 已支持项目的完整 course/prerequisite dependency closure。

### 12.3 版本和冲突

- Program requirements 必须携带 catalog year；
- 动态 deadline 必须携带 term；
- 页面更新后保留内容 hash 和抓取时间；
- Current policy 与 archived requirement 不得混为同一个无版本 chunk；
- 冲突时按问题类型选择 authority，不使用一个全局权重解决所有冲突；
- 无法确定学生适用版本时，返回需确认状态。

### 12.4 Eval 驱动摄入

每批新来源必须：

1. 对应一个明确的问题覆盖缺口；
2. 先添加或更新 retrieval/behavior case；
3. 运行 vector/hybrid 和 scope regression；
4. 确认 restricted leakage 为 0；
5. 确认没有错误学院政策进入答案；
6. 记录新来源的 authority、validity 和 owner。

---

## 13. 数据、隐私与安全

### 13.1 数据分类

| 数据 | 分类 | 处理原则 |
|---|---|---|
| 公开政策和课程目录 | Public | 可抓取快照并引用原链接 |
| 自报课程记录 | Student-provided | 仅当前用户可读写 |
| 成绩单文件 | Highly sensitive transient | 解析后立即丢弃，不持久化 |
| OCR 图片 | Highly sensitive transient | 外部处理前明确披露 |
| Chat history | Sensitive | 限量、可清除，不授予工具权限 |
| Audit log | Restricted operational | 最小化访问、定义保留周期 |
| Demo student data | Synthetic | 与真实 catalog/source 明确隔离 |

### 13.2 安全要求

- 所有 student-specific tool 使用服务器注入身份；
- 不允许模型指定数据主体；
- 所有资源 route 进行 ownership 验证；
- 检索 RBAC 必须在候选生成前执行；
- Citation source ID 必须在本轮工具结果集合中；
- 上传限制大小、类型和解析资源消耗；
- 日志不得保存原始 transcript bytes 或 OCR 图片；
- Production 禁止开启 fault injection；
- Session secret、模型 key 和 OCR provider key 不得进入前端或仓库。

### 13.3 Beta 前必须拍板

- Chat 和 audit log 的保留周期；
- 用户删除账户/数据的流程；
- OCR provider 的数据处理披露；
- 是否保存 conversation thread；
- Live mode 是否允许创建任何 case，还是只生成 handoff；
- 使用条款、免责声明和隐私说明。

---

## 14. 非功能需求

### 14.1 性能

- 非 LLM 页面 API：P95 小于 1 秒（不含冷启动和外部依赖）；
- Agent 首个真实状态事件：目标小于 1 秒；
- Agent 完整回答：P95 目标小于 20 秒；
- Sequence 计算必须有超时和可解释失败；
- 上传解析对最大允许文件有确定资源上限。

### 14.2 可用性

- Embedding、LLM、OCR、数据库和 retrieval empty 各有明确降级路径；
- 降级不得放宽权限或把空数据解释成安全状态；
- 卡片操作必须具备幂等或重复操作安全行为；
- 同一资源在多个标签页修改后能够检测 stale 状态。

### 14.3 可访问性

- WCAG 2.1 AA 为最低标准；
- 状态不只通过颜色表达；
- 所有表单有 label；
- 动态运行状态使用可访问 live region；
- 所有动作可由键盘完成；
- 证据 highlight 在无颜色环境下仍能识别；
- 移动端最小触控目标、文字缩放和横向溢出必须经过实际验证。

### 14.4 可观测性

- 每轮记录 interaction ID、latency、iterations、token usage 和 degraded modes；
- 每个工具调用记录参数摘要、iteration、source IDs、失败状态和耗时；
- 监控 forbidden writes、citation rejection、retrieval miss、OCR failure 和 case escalation；
- 生产日志不得泄露成绩单或不必要的学生详情。

---

## 15. 成功指标与评测门槛

### 15.1 North Star

**Verified Planning Completion Rate**：学生会话最终产生以下任一结果的比例：

- 一份带来源、可审阅的规划方案；
- 一个明确、正确分类的限制/不确定状态；
- 一个恰当的人工 handoff；

且全程没有越权读取、伪造来源或未授权实质写入。

### 15.2 产品指标

| 指标 | Beta 目标 |
|---|---:|
| 新用户完成首次 profile 建立 | ≥ 70% |
| Profile 就绪后 2 分钟内得到首个有用 artifact | ≥ 80% |
| 用户能正确区分 proposed 与 confirmed | ≥ 90%（可用性测试） |
| 核心卡片操作无需跳转完整工具页 | ≥ 90% |
| Agent 回答 P95 | < 20 秒 |
| 首个真实进度事件 | < 1 秒 |
| 用户报告“答案引用了错误学院政策” | 0 |

### 15.3 当前技术基线

截至 2026-08-10 的已记录结果（`api/eval/results/report-20260810-193648.md`，gate PASS）。
会在运行之间波动的指标写区间，取值来自实际记录的多次运行而不是最好的一次：

- Retrieval：Recall@5 0.91，MRR 0.815；
- Agent behavior：35/35 cases（**部分运行为 34/35**，单个 borderline 案例翻转）；
- High-stakes escalation recall：1.0（**部分运行为 0.89**——9 个高风险案例中翻转 1 个即低于
  0.90 的自身门槛；两种结果都在同一份代码上被记录过，见 `report-20260807-224621`）；
- Citation coverage：0.9565；
- Leakage failures：0；
- Forbidden tool calls：0；
- Decoder：accuracy when named 1.0，confidently wrong 0；
- Transcript：row recall 1.0，silently wrong 0；
- OCR：3 个图片 fixture 行召回 1.0，已知 1 个字段错误，全部强制 review；
- 权限边界：authz_probe 28/28，其中 23 条断言“被禁止的动作确实失败”。

### 15.4 持续门槛

- `leakage_failures = 0`；
- `forbidden_tool_calls = 0`；
- `intake_silently_wrong = 0`；
- `decoder_confidently_wrong = 0`；
- `decoder_unsafe_hold_reads = 0`；
- `decoder_ambiguity_held = 1.0`；
- retrieval recall@5 不低于当前 regression floor；
- citation coverage 不低于 0.90；
- 每条新写工具必须有 forbidden-call 测试；
- 每个新语料族必须有 retrieval cases。

这些门槛是 regression gate，不等同于真实世界质量证明。Beta 需要额外 held-out queries 和真实用户任务测试。

---

## 16. 发布路线图

### Release 1：产品契约与语料治理

目标：让现有能力具备更可靠的来源和稳定 UI 协议。

- 正式 Artifact Contract；
- 标准化 source/provenance registry；
- Production、conditional、eval corpus 分层；
- 补齐 university-wide、Registrar、Bursar、Financial Aid 语料；
- catalog year 和 source authority metadata；
- 修复 live user school/program scope；
- 对 vector/hybrid 默认策略重新做同集对比。

退出条件：核心问题覆盖矩阵达到约定水平，错误学院引用为 0，所有 artifact 有契约测试。

### Release 2：真实过程可见性与上下文预算

目标：长任务可理解、可取消、可恢复。

- 工具事件级 SSE；
- tool started/completed/failed 文案；
- conversation token budget；
- freshness-aware state summary；
- thread persistence 是否上线的产品决策；
- stale artifact 和跨标签页冲突处理。

退出条件：首个真实状态事件小于 1 秒，断线和重连不造成重复写入。

### Release 3：Invite-only Beta

目标：允许少量真实 SPS 学生安全试用。

- Rate limits 和 per-user cost ceiling；
- 隐私、数据保留和删除流程；
- OCR disclosure；
- Production secrets 和 HTTPS session；
- 可访问性与移动端审查；
- 监控、告警和故障演练；
- Feedback 入口和 held-out eval 数据收集。

退出条件：安全门槛全部通过，四类依赖故障路径实际验证，用户能够识别产品非官方性质。

### Release 4：Program Expansion

目标：把高置信 planning 扩展到第二个 SPS graduate program。

- 选择一个需求明确、规则可编码的项目；
- 完整 requirements/course dependency closure；
- catalog-year fixtures；
- 新 program 的 planner、sequence、retrieval 和 transcript eval；
- 证明扩展不会把一个项目规则应用到另一个项目。

退出条件：新项目达到与首个项目相同的确定性规则和安全门槛。

---

## 17. Beta 发布验收标准

必须全部满足：

### 功能

- 新用户可以通过手动输入或 transcript review 建立 profile；
- 学生可以在 Chat 内生成一轮规划并处理 candidate；
- Mission、Sequence、Decoder 和 Intake 都有完整 happy path 与恢复路径；
- Live mode 不显示虚假的官方记录或 staff case 承诺；
- 所有核心来源可打开并显示时效和适用范围。

### 安全

- 跨用户和跨角色访问测试为 0 泄漏；
- Agent 无法确认 candidate、接受 risk 或修改官方状态；
- 成绩单文件和图片不持久化；
- OCR 前披露外部处理；
- 所有生产 secrets 已替换开发默认值；
- Fault injection 在 production 强制关闭。

### 质量

- 全量 unit/eval gate 通过；
- Agent、retrieval、decoder、sequence、mission、intake 都有回归覆盖；
- Chrome/Firefox/Safari 当前版本完成关键流程；
- 375px、768px、1280px 关键断点无阻断性问题；
- 键盘、focus、screen reader status 和颜色对比通过审查；
- 所有可见控件有真实结果，不存在占位动作。

### 运营

- 有请求限流、模型成本上限和基础告警；
- 有隐私说明、免责声明和问题反馈渠道；
- 有语料更新流程和 source owner；
- 有故障时的用户文案和人工处理方式；
- 有停止 beta 或回滚高风险能力的开关。

---

## 18. 主要风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 语料不完整 | 回答有引用但仍遗漏关键规则 | 覆盖矩阵、authority metadata、eval-driven ingestion |
| 错学院/错版本政策 | 权威地给出错误结论 | 适用性硬过滤、catalog year、冲突状态 |
| 学生自报记录错误 | 所有下游规划被污染 | 明确自报、review、可编辑、重新计算 |
| Course offering 缺失 | Sequence 看起来过度确定 | 每个 placement 单独标记 assumption |
| OCR 字段误读 | 错误课程或成绩进入 profile | OCR 永不 matched、逐项 review、原文对照 |
| 模型产生无效工具路径 | 慢、贵、用户等待 | 搜索预算、轨迹 eval、事件流、迭代上限 |
| Chat 历史污染事实 | 旧状态被当成当前状态 | 历史只存文本、事实每轮重取 |
| Artifact action 重复执行 | 状态不一致 | canonical ref、幂等、stale detection |
| Live escalation 造成虚假承诺 | 学生等待不存在的回复 | 只生成 handoff，不声称已联系 NYU |
| Agent-first 变成文字墙 | 用户无法审阅方案 | Artifact 优先层级、分节 review、完整状态设计 |

---

## 19. 待决策问题

1. Beta 是否持久化 conversation thread？如果持久化，保留多久、如何删除？
2. Artifact 是随 interaction 保存快照，还是只保存 canonical resource reference？
3. Production 是否默认开启 hybrid retrieval？必须以同一 eval 集对比后决定。
4. Peer-school policies 是否完全移出 production corpus，还是保留 explicit cross-registration scope？
5. 第二个支持的 SPS program 是什么，选择依据是用户需求还是规则可编码性？
6. OCR provider 的隐私条款和地区处理是否满足 beta 要求？
7. Live 用户出现高风险问题时，产品只生成 handoff，还是允许用户主动创建本地 follow-up task？
8. 是否需要让学生选择 catalog year，还是能从入学信息可靠推导？
9. 真正 token streaming 是否带来足够价值，还是工具事件流已经解决等待问题？

---

## 20. 术语

- **Artifact**：由工具或确定性引擎产生、可在对话内查看和操作的结构化结果。
- **Mission**：针对某一 term 的注册准备任务容器，状态由事实推导。
- **Candidate**：建议用于 mission term 的课程；`proposed` 不代表学生选择。
- **Sequence**：在约束下计算出的剩余课程学期顺序。
- **Decoder**：对注册错误文本进行确定性分类和证据高亮的工具。
- **Profile**：学生在 Path Pilot 中主动提供的课程记录，不是官方 transcript。
- **RAG**：只用于检索政策和公开资料证据，不负责替代确定性规划计算。
- **Source ID**：工具为本轮事实返回的可验证来源标识。
- **Degraded mode**：外部依赖不可用时，系统采用受限替代路径并向用户披露。
- **Live mode**：真实用户模式；无 Albert 或校内 staff workflow。
- **Demo mode**：使用虚构且内部一致的学生、holds、attempts 和 case queue。

---

## 21. 产品完成定义

一个功能只有同时满足以下条件才算完成：

1. 用户任务和非目标明确；
2. 权限与 Agent 动作边界明确；
3. Happy path 以及 loading、empty、error、permission、stale、degraded 状态可达；
4. 事实来源、适用范围和时效可见；
5. 确定性计算与模型生成职责没有混淆；
6. 对应 API、UI、权限和 eval 测试存在；
7. 在实际桌面和移动断点完成渲染审查；
8. 没有无效控件、假数据或可套用到任意产品的通用 dashboard 内容；
9. 文档更新了真实限制，而不是只描述理想能力。
