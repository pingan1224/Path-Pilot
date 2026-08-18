# M12-B 方案：限流与成本上限

2026-08-18 制定，基线 `main@2797b9f`。

现状一句话：产品的每一轮对话都在花钱，而**除了单轮预算之外没有任何速率或总量限制**——
demo 密码是公开印在 `/demo` 页面上的，所以「谁能刷、能刷多少」这个问题目前的答案是「任何
人，无上限」。这是 F2 邀请码和 F3 自助注册被显式 gate 在 M12 之后的原因，也是 PRD Release 3
「有请求限流、模型成本上限和基础告警」这一条至今未完成的部分。

本方案只覆盖 M12-B 的限流与成本部分。隐私、数据保留、可访问性审查、告警演练同属 Release 3，
不在此展开。

---

## 现在已经有的，和现在没有的

**已经有的是单轮预算，不是速率限制。** 两者防的东西不一样，容易被当成同一件事：

| 已有机制 | 位置 | 限制的是 |
|---|---|---|
| `MAX_ITERATIONS = 6` | `services/agent.py` | 一次提问内最多几次模型调用 |
| `MAX_POLICY_SEARCHES` | `services/agent_tools.py` | 一次提问内最多几次检索 |
| `max_tokens = 4096` | `services/llm.py` | 单次模型调用的输出长度 |

这三个都把**一次提问**的成本封了顶。没有任何东西限制**提问的次数**。一个循环脚本拿公开的
demo 密码登录，就能以每轮约 8500 input / 760 output token 的速度持续消耗，直到额度耗尽。

**已经有的还有一份账本。** `ai_interactions` 每一行都记着 `model`、`input_tokens`、
`output_tokens`、`latency_ms`、`occurred_at`。这意味着成本上限不需要新建计量设施——写这份
方案时它已经在按轮记账了，只是没人读它做决策。

---

## 要防的是三件不同的事

把「限流」当成一件事去做，做出来的东西通常既拦不住账单，又会误伤真实用户。拆成三层：

| 层 | 防什么 | 计数维度 | 优先级 |
|---|---|---|---|
| **A. 登录限流** | 公开 demo 密码被脚本利用、撞库 | IP | 中 |
| **B. 模型调用配额** | 单个账号刷对话 | 用户 | 高 |
| **C. 全局成本熔断** | A、B 都被绕过时的最后防线 | 全站 | **最高** |

C 是唯一真正保护账单的东西，A 和 B 的作用是让 C 不要轻易触发。如果只做一件，做 C。

---

## 存储选型：必须落库，不能放内存

这一条由部署形态决定，不是偏好。

Render 免费层 `numInstances: 1`，看起来进程内计数器就够。但**实例在约 15 分钟无请求后休眠**，
醒来是全新进程——内存里的计数全部归零。攻击者只需要每 16 分钟停一次，配额永远刷不满。
2026-08-18 排查线上问题时实测的冷启动是 31 秒，那次是它的另一面。

所以计数落 Postgres。代价是每个受限请求多一次写入，对比一次模型调用 11 秒、8500 token，可以
忽略。附带好处是将来扩到多实例不用重写。

```sql
CREATE TABLE IF NOT EXISTS rate_events (
    bucket       VARCHAR(64)  NOT NULL,   -- 'login:203.0.113.7' / 'ask:user:42'
    window_start TIMESTAMPTZ  NOT NULL,
    count        INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, window_start)
);
```

固定窗口而非滑动窗口：`INSERT ... ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`
一次往返拿到当前值。滑动窗口更精确，但要为每次请求存一行明细并定期清理，在这个量级上买到的
精度不值那个复杂度。窗口边界处允许两倍突发，是接受的代价。

---

## A. 登录限流

**同一 IP 每 15 分钟 10 次登录尝试。**

成功和失败都计数。只计失败是常见写法，在这里是错的：demo 密码是公开的，攻击者每次都「成功」，
一次都不会被记。

IP 从 Render 转发的 `X-Forwarded-For` 最左一跳取，不能直接读 socket 地址——那是平台代理的
地址，所有人共用一个，一旦触发就是全站锁死。

---

## B. 模型调用配额

**限的是模型轮次，不是 HTTP 请求。** 一次 `/assistant/ask` 内部最多 6 次模型调用，按请求计数
会低估六倍。

demo 账号和受邀用户必须分档——公开密码的那一档是主要攻击面：

| 账号类型 | 每日模型轮次 | 依据 |
|---|---:|---|
| demo 种子账号 | 20 | 走完产品四个页面加几轮追问绰绰有余 |
| 受邀真实用户 | 100 | F2 之后才存在；正常使用远低于此 |
| 未登录 | 0 | 这两个端点本来就要求会话 |

**挂成端点依赖，不做全局中间件。** `/health/ready`、`/catalog/programs` 这类便宜的读没有理由
和模型调用共用一套规则，把它们一起拦住是限流做错时最典型的症状。只挂在真正花钱的两个端点：

- `POST /assistant/ask`
- `POST /intake/transcript`（视觉识别，单次比一轮对话更贵）

---

## C. 全局成本熔断

账本已经在了，直接读：

```sql
SELECT coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0)
FROM ai_interactions
WHERE occurred_at > now() - interval '24 hours';
```

超过阈值即拒绝新的模型调用，直到窗口滚过。这正是 PRD Release 3 运营清单里那条「**有停止 beta
或回滚高风险能力的开关**」——它不需要是一个手动开关，自动的更可靠。

**阈值用 token 数表达，不用美元。** 定价会变而且随供应商不同，把美元写死在代码里，就会重演
`CHAT_MODEL` 那种「真相源有两个，其中一个悄悄过期」的问题。运营者按当期账单换算即可。参考
量级：2026-08-18 线上一轮真实对话是 8554 input / 758 output。

---

## 触发之后的行为：复用现有词汇，不发明新的失败形状

这是本方案最重要的约束。

这个产品已经有一套成熟的降级表达：`degraded_modes` 里有 `retrieval_budget_exhausted`、
`keyword_fallback`、`llm_error`、`program_not_encoded`。限流应该长成它们的同类，而不是一个
突兀的 429 JSON——否则前端要为一种新的失败形状写新组件，而它已经会渲染降级横幅和「带去找
advisor」卡片了。

具体：

- HTTP 层返回 **429**，带 `Retry-After`
- 对 `/assistant/ask`，响应体沿用现有的 `deferred` 决策形状，新增一个 degraded mode：
  **`rate_limited`**
- 文案必须说清楚这是配额不是故障，以及什么时候恢复

反例是「服务暂时不可用，请稍后再试」——它把一个确定的、有明确恢复时间的限制，说成了一次
不确定的故障。规则 6：说清楚缺的是什么，而不是安静地失败。

建议文案：

> You have used today's question allowance for the demo account. It resets at 00:00 UTC.
> Nothing here failed — this is a cost limit on a personal project.

---

## 验收方式

照项目现有习惯：故障注入 + probe 脚本，而不是只有单元测试。

`app/faults.py` 增加两个键：

```python
"rate.user_quota_spent": "The per-user model quota is already spent; the turn must end as rate_limited, not a 500."
"rate.global_ceiling":   "The global daily token ceiling is reached; no model call may be made."
```

新增 `scripts/rate_limit_probe.py`，与 `authz_probe.py`、`fault_probe.py` 并列。断言三件事：

1. 配额耗尽后 `/assistant/ask` 返回 `decision=deferred` + `degraded_modes=['rate_limited']`，
   **不是 500**
2. 配额耗尽**不影响**只读端点——planner / mission / sequence 照常 200
3. 登录限流触发后，**正确的密码也会被拒**；否则限流形同虚设

第 2 条是最容易做错的一条。限流实现失误的典型表现不是拦不住，而是把整个产品锁死，而不只是
锁住花钱的部分。

---

## 实施顺序

| 步骤 | 内容 | 估计 |
|---|---|---|
| 1 | `rate_events` 表 + migrate 语句 + 计数原语 | 0.5 天 |
| 2 | **C 全局熔断**（复用 `ai_interactions`，最省事、保护最大） | 0.5 天 |
| 3 | B 按用户配额 + `rate_limited` degraded mode + 前端文案 | 1 天 |
| 4 | A 登录限流 | 0.5 天 |
| 5 | faults 键 + probe 脚本 | 0.5 天 |

合计约 3 天。

**只想止血就做第 2 步**：半天，不依赖第 1 步（它读的是已有的 `ai_interactions`)，直接盖住
「账单被刷爆」这个最坏结果。其余四步可以按自己的节奏补。

---

## 与 F2 / F3 的关系

M12-B 完成后：

- **F2 邀请码激活**解锁——`invite_codes` 表 + `POST /auth/redeem` 自设密码，邀请码发到邮箱、
  投递即身份验证，不需要邮件服务（见 `roadmap-m13-m16.md`)
- **F3 自助注册**仍需单独立项：它还要邮箱验证、找回密码和完整的滥用防护

在此之前，开真实账号的唯一方式是 `scripts/create_user.py`，由运维执行。这个顺序是刻意的：
**在没有限流的情况下开放自助注册，等于把账单开放给全互联网。**
