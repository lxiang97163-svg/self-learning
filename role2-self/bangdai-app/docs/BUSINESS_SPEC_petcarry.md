# CarryLink 宠物帮带 实施规格 v0.1

> 本文件由 `business-idea-exploration` Skill 流程产出。**非法律意见、非投资建议。** 合规须咨询执业律师及目的地海关/检疫机关。

## 1. 问题陈述与非目标

**问题陈述（Spec）**  
国际航线上，宠物随行/托运需求与「有舱位/余量可协助」的旅客之间**匹配成本高、信任难建立**。CarryLink（宠物帮带垂直）提供**信息发布与撮合沟通**，首期聚焦少数国家/城市航线簇，验证双边流动性与收费可行性。

**非目标（Spec）**  
- 平台不运输、不囤货、不代理报关、不提供应用内支付。  
- 本期不承诺动检文件代办、不接入保险/支付托管。  
- 不做全球全航线泛化运营（运营上可逐步扩线）。

**成功长什么样（Spec）**  
供需双方在站内完成发现→兴趣→接受→沟通→约定金额记录→交割完成标记；管理员可审计帖子与举报。

---

## 2. 用户与场景（Spec）

- **携带方（旅客）**：发布国际航班行程、可接受的宠物类型/体重上限、计价方式。  
- **需求方（宠物主/委托人）**：发布目的地、时间窗口、宠物种类与体重、说明与预算。  
- **管理员**：用户与帖子列表、举报查看。

---

## 3. 竞品与差异化（检索来源简述）（Spec + Context）

| 名称 | 模式 | 备注 |
|------|------|------|
| CitizenShipper（美） | C2C 宠物/货运竞价撮合 | 地面运输为主；公开信息称背景核查、保险等（**未逐条核实条款**）。 |
| Anilogistic 等 | 类似 C2C | 作类比，细节未验证。 |

**差异化（推断）**：聚焦**国际航班场景**与**中文用户**，从少数航线切入；产品形态为轻量撮合 + 合规模板，与全美地面车运平台不同。

---

## 4. Harness：合规、安全、免责声明要点（非法律意见）

- **动物检疫与入境**：各国对活体入境要求差异极大；用户须自行完成申报与许可，平台不提供法律保证。  
- **平台责任边界**：撮合与信息展示；纠纷与履约在线下；模板须本地律师审阅后上线。  
- **资金**：无应用内支付则无沉淀资金；若未来接入托管，须另评支付/牌照（Harness，待核实）。  
- **数据与账号**：密码 bcrypt；最小必要个人信息；密钥仅存环境变量。  
- **UGC**：禁运与举报流程；管理员事后处置占位。

---

## 5. MVP 功能与验收（用户故事 + 验收）

- 注册/登录；发布/浏览「携带意向」与「帮带需求」；同目的地匹配；兴趣→对方接受→站内消息；记录约定金额与平台费试算；标记完成；法务页与确认勾选；举报；Admin 列表。

**Given–When–Then 示例**  
- Given 双方已接受撮合，When 任一方输入约定金额并保存，Then 显示平台费试算且可标记完成。

---

## 6. 数据模型草案（Spec）

- `User`  
- `PetCarryOffer`：行程、物种接受范围、最大体重、客舱/托运意向、计价、状态  
- `PetCarryNeed`：目的地、时间窗口、宠物种类/体重/说明、预算、状态  
- `PetCarryMatch`：offerId+needId 唯一、状态机  
- `CommissionRecord`、`Message`、`Report`（关联撮合单）

---

## 7. 页面/路由清单（Spec）

- `/` 首页  
- `/offers`、`/offers/new`、`/offers/[id]`  
- `/needs`、`/needs/new`、`/needs/[id]`  
- `/matches/[id]`、`/messages`、`/messages/[threadId]`  
- `/legal/disclaimer`、`/legal/prohibited`  
- `/admin`

---

## 8. 关键流程（Spec）

注册 → 发布携带意向/需求 → 列表筛选 → 表达兴趣（绑定对方帖子）→ 对手方接受 → 消息线程 → 约定金额 → 完成。

---

## 9. 非功能需求（Context）

- 中文 UI；SQLite + Prisma 演示；E2E 覆盖主路径；性能与 SEO 本期从简。

---

## 10. 开放问题（待决策）

- 首期开放航线列表是否在 UI 硬编码提示（示范）？  
- 物种匹配是否做强校验（本期可仅目的地一致）？

---

## 层级索引

- **Harness**：第 4 节  
- **Spec**：第 1、2、5～8 节  
- **Context**：第 3、9 节  

---

## Phase 7：实施级终极 Prompt（给开发 Agent）

```text
【Harness｜缰绳】
- 法律与合规（非法律意见）：平台仅撮合与沟通；不运输、不支付、不代理报关；宠物检疫与入境由用户自负；法务页为模板须律师确认。
- 安全与隐私：NEXTAUTH_SECRET、DATABASE_URL；密码 bcrypt；最小收集。
- 本期范围锁死：不做应用内支付、托管、KYC、自动海关规则引擎。Phase 2：支付分账、保险、强验证。

【Spec｜规格】
- 产品目标：宠物帮带垂直；路由 /offers /needs；实体 PetCarryOffer / PetCarryNeed / PetCarryMatch。
- 角色：user、admin。
- 核心字段：Offer 含 acceptedSpecies、maxPetWeightKg、carryMode、priceModel(perPet|fixed)；Need 含 petSpecies、petWeightKg、petNotes。
- 撮合：同目的地；兴趣双向发起二选一；接受后关帖。
- 验收：build/lint 通过；E2E 注册→发布→兴趣→接受→消息→金额→完成。

【Context｜上下文】
- Next.js 14 App Router、Prisma、SQLite、NextAuth Credentials。
- 品牌：CarryLink 宠物帮带；语气专业、风险提示醒目。

【Agentic｜实现顺序】
1）schema + db push  2）actions  3）页面与导航  4）E2E  5）文档

【验收】
- npm run lint && npm run build；npm run test:e2e（本机）。

【Vibe】
- 清晰、可信赖、合规提示可见；避免「万能帮带」表述。

第一版目标为可验收，不承诺零缺陷；以本验收清单为完成定义。
```
