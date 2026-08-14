/**
 * UI chrome strings, Simplified Chinese. Covers exactly the key set in en.js; any key
 * missing here falls back to English rather than rendering the raw key.
 *
 * Server-sent content (assistant answers, mission steps, blockers, citations) stays in
 * English by design — see the note in en.js. Course codes, term names ("Fall 2026") and
 * proper nouns (Albert, NYU SPS) are not translated: they must match what the student
 * sees in Albert, or the instruction "check Albert" points at nothing.
 */
export const zh = {
  // Shell chrome
  "app.name": "Path Pilot",
  "app.tagline": "纽约大学专业研究学院",
  "sidebar.mission.label": "注册任务",
  "sidebar.mission.steps": "已完成第 {done} / {total} 步",
  "palette.placeholder": "提问或跳转至…",
  "palette.navigate": "导航",
  "palette.go": "跳转",
  "palette.close": "关闭",
  "shell.skip": "跳到正文",
  "shell.back": "← 返回助手",
  "shell.signout": "退出登录",
  "pane.label": "侧栏视图",
  "pane.drawer": "就绪状态",
  "pane.focused": "仅对话",
  "pane.audit": "核查记录",

  // Navigation
  "nav.chat": "问问 Path Pilot",
  "nav.chat.sub": "提问、贴报错、规划学期",
  "nav.planner": "学位进度",
  "nav.planner.sub": "还差哪些课",
  "nav.planner.sub.live": "已修 {done} / {total} 学分",
  "nav.mission": "注册任务",
  "nav.mission.sub": "为一个学期做好准备",
  "nav.mission.sub.blocked": "受阻 · {count} 项",
  "nav.mission.sub.step": "第 {step} / {total} 步 · {term}",
  "nav.mission.sub.ready": "已就绪 · {term}",
  "nav.intake": "成绩单",
  "nav.intake.sub": "PDF 或成绩单照片",
  "nav.intake.sub.live": ({ count }) =>
    count > 0 ? `记录中有 ${count} 门课` : "记录还是空的",
  "nav.sequence": "排课规划",
  "nav.sequence.sub": "到毕业的每个学期",
  "nav.sequence.sub.live": "{term} 排课",
  "nav.decoder": "解读报错",
  "nav.program": "你的项目",
  "nav.dashboard": "总览（演示）",
  "nav.heading": "记录与工具",
  "rail.program.eyebrow": "在读项目",
  "rail.program.open": "打开项目设置",

  // Rail
  "rail.aria": "选课就绪状态与工具",
  "rail.program.unset": "请设置你的学位项目",
  "rail.program.unset.meta": "学位进度、排课和注册任务都需要知道哪套规则适用于你。",
  "rail.program.unset.action": "需要操作",
  "rail.program.choose": "选择学位项目",
  "rail.program.encoded": "培养方案已录入——可查看学位进度",
  "rail.program.notEncoded": "培养方案未录入——仅支持政策问答和报错解读",
  "rail.program.full": "完整规划支持",
  "rail.program.limited": "部分支持",
  "rail.failed": "无法读取你的记录",
  "rail.failed.meta": "是读取失败，不是空记录——此刻这里的一切均属未知。",
  "rail.failed.retry": "重试读取记录",
  "rail.recomputed":
    "每次读取都会重新计算。已修课程为自行申报——Path Pilot 无法访问 Albert。",
  "rail.disclaimer":
    "个人作品集项目——并非 NYU 官方系统。学生与记录均为虚构；政策文本引自 NYU 公开的培养手册并附来源链接。",

  // Preferences
  "prefs.theme": "主题",
  "prefs.theme.auto": "跟随系统",
  "prefs.theme.light": "浅色",
  "prefs.theme.dark": "深色",
  "prefs.lang": "语言",

  // Chat — landing
  "chat.hero.title": "下学期该修什么？",
  "chat.hero.desc":
    "我只读取 NYU 公开发布的规则和你录入的课程——除此之外别无其他。我看不到 Albert，" +
    "所以凡是无法核实的，我会明确指出，而不是猜测。",

  // Chat — computed greeting
  "greet.hi": "你好 {name}——{status}",
  "greet.recovered": "你的记录已恢复可读——{status}",
  "greet.mission": ({ term, done, total, next }) =>
    `你的 ${term} 注册任务已完成 ${done}/${total} 步。` + (next ? `下一步：${next}` : ""),
  "greet.courses": "记录中有 {count} 门课程，还没有正在准备的学期。",
  "greet.empty": "记录还是空的。",
  "greet.failed":
    "你好 {name}——刚才没能读取你的记录，所以无法说明你的注册进展。这是连接问题，" +
    "不代表记录为空。我仍可以解读注册报错和公开政策——两者都不需要读取记录。",

  // Chat — suggestion chips
  "chip.next": "下学期我该修什么？",
  "chip.suggest": "为我的注册任务推荐课程",
  "chip.plan": "规划我的下个学期",
  "chip.delay": "跳过哪门课会拖延我毕业？",
  "chip.prereq": "ERR_PREREQ 是什么意思？",
  "chip.first": "我该先做什么？",
  "chip.holds": "注册 hold 是怎么回事？",

  // Chat — answer frame
  "kicker.answered": "基于已核实来源作答",
  "kicker.caveat": "已作答——请留意注意事项",
  "kicker.escalated": "已转交人工处理",
  "kicker.refused": "超出可核实范围",
  "chat.you": "你",
  "chat.assistant": "Path Pilot",
  "chat.case": "已开立工单 {number}——联系相关办公室时请引用此编号。",
  "chat.degraded": "降级运行——",
  "chat.boundary":
    "我可以阅读公开规则、解释你录入的信息意味着什么、并向对应办公室开立工单。" +
    "我不能解除 hold、免除先修要求、批准例外或更改你的注册——这些决定权在相应办公室。",
  "chat.checked": "已核查：{tools}",
  "chat.citations": "{count} 条已引用的论断",
  "chat.error.kicker": "无法作答",
  "chat.error.retry": "重新提问",

  // Chat — header and frame
  "chat.subtitle": "基于你的记录与公开政策作答",
  "chat.ready": "就绪",
  "chat.sources": "来源",
  "chat.sourcesUsed": "已引用 {count} 个来源",
  "chat.footer": "回答均注明来源——任何影响注册的事项请先在 Albert 核实。",

  // Chat — waiting
  "chat.thinking": "正在按需核查你的记录、政策与规划 · ",
  "chat.thinking.long": " · 仍在处理，答案越长意味着查询越多",

  // Chat — composer
  "chat.placeholder": "问问下学期修什么、粘贴选课报错，或查查学位进度…",
  "chat.ask": "提问",
  "chat.ask.label": "提出问题",
  "chat.send": "发送",
  "chat.disclaimer":
    "回答会注明依据，并说明哪些内容无法核实。这不是 NYU 系统，也看不到 Albert——" +
    "任何影响注册的事项，请先在 Albert 核实再行动。",

  // Audit pane
  "audit.title": "核查记录",
  "audit.desc": "每次查询都先按你的记录做权限过滤，并写入审计日志。",
  "audit.empty": "还没有内容——提问后这里会逐条填入。",
  "audit.aria": "助手核查了什么",
  "audit.failed": "查询失败——未计入回答",
  "audit.sources": "返回 {count} 个来源",
  "audit.noSources": "未返回可引用来源",
  "audit.degraded": "降级运行",

  // Tool labels
  "tool.search_policy": "政策检索",
  "tool.get_course_info": "课程目录",
  "tool.get_my_plan": "你的计划",
  "tool.albert_checklist": "Albert 查看指引",
  "tool.decode_registration_error": "报错解读",
  "tool.get_mission_state": "任务状态",
  "tool.propose_mission_candidates": "课程建议",
  "tool.get_course_sequence": "学期排课",
}
