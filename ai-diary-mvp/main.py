import base64
import json
import os
from typing import List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

load_dotenv()

app = FastAPI()

STYLES = {
    "healing": ("治愈风", "温暖治愈、细腻感性，像在和老朋友倾诉，充满温度与感恩"),
    "literary": ("文艺风", "文艺唯美、意境深远，善用比喻与意象，有诗意的留白"),
    "humorous": ("幽默风", "轻松幽默、自嘲有趣，用好玩的视角记录生活的小确幸"),
}

MIME_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
}

# ── 文风分析 Prompt（遵循 AGENT_USER_STYLE_PROFILE.md 规范）─────────────────
STYLE_ANALYSIS_PROMPT = """你是「文风沉淀」Agent。请分析以下私人文字样本，输出一份可供生文 Agent 直接执行的 StyleBrief。

**StyleBrief 结构（严格按序，总长不超过 600 字）**

1. 【口吻】一句话：第一人称 / 第二人称；私密程度；语气与距离感。

2. 【高优先级签名】3-5 条稳定特征（syntax / lexicon / scaffold 层），每条附 ≤15 字的短引证或 paraphrase；禁止无引证结论。

3. 【generation_contract】
   must（3条）：下游必须执行、可一眼判是/否的硬规则。
   avoid（3条）：必须避免、可一眼判是/否的硬规则。
   （示例好格式：「结尾不用排比金句」「感叹号全文 ≤2」——不写「要真实自然」之类无法检验的描述）

4. 【style_anchor】原创仿写 2 句：不抄原文，只复现节奏/口气/连接方式，用无害占位内容，标注 (style_anchor)。

**置信度**：样本约 {char_count} 字，若 < 200 字请注明「样本偏短，置信度 low，以下为推断」。

【文字样本】
{sample}

请直接输出 StyleBrief，不输出任何其他内容。"""


async def analyze_style(sample: str, api_key: str) -> str:
    """Step 1: 分析用户文风，返回 StyleBrief 字符串。"""
    prompt = STYLE_ANALYSIS_PROMPT.format(
        char_count=len(sample),
        sample=sample.strip(),
    )
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 900,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"文风分析失败: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_prompt(style: str, photo_count: int, style_brief: str = "") -> str:
    """构建生成 prompt。custom 风格使用 StyleBrief；其余使用预设风格描述。"""
    base_rules = (
        f"- 字数：200-400字\n"
        f"- 以第一人称书写，像是在回忆这段经历\n"
        f"- 照片有备注的，请结合备注内容准确描述，备注优先于视觉判断\n"
        f"- 不要逐一描述每张照片，融合成一段有起伏的叙事\n"
        f"- 不要出现照片、图片等词汇，就像真实的亲历者在回忆"
    )

    if style == "custom":
        return (
            f"你是一位专业的文字创作者。请严格遵照下方【写作风格规格】，"
            f"根据以上 {photo_count} 张照片写一段日记式叙事记录。\n\n"
            f"【写作风格规格（StyleBrief）】\n{style_brief}\n\n"
            f"生成规则：\n"
            f"- 先读 StyleBrief，再读 generation_contract 中的 must / avoid，逐条执行\n"
            f"- 若 StyleBrief 中有 style_anchor 仿写句，以其节奏为对齐基准\n"
            f"{base_rules}"
        )

    style_name, style_desc = STYLES.get(style, STYLES["healing"])
    return (
        f"请根据以上{photo_count}张照片，用{style_name}写一段日记式的叙事记录。\n\n"
        f"要求：\n"
        f"- 风格：{style_desc}\n"
        f"{base_rules}"
    )


@app.post("/api/generate")
async def generate(
    photos: List[UploadFile] = File(...),
    notes: str = Form("[]"),
    style: str = Form("healing"),
    custom_sample: str = Form(""),
):
    if len(photos) > 20:
        raise HTTPException(status_code=400, detail="最多上传20张照片")

    if style == "custom" and not custom_sample.strip():
        raise HTTPException(status_code=400, detail="请粘贴一段你的文字，AI 才能学习你的文风")

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API key 未配置")

    # Step 1: 自定义文风 → 先分析样本，提取 StyleBrief
    style_brief = ""
    if style == "custom":
        style_brief = await analyze_style(custom_sample, api_key)

    # Step 2: 构建多模态 content（照片 + 备注 + 生成 prompt）
    notes_list: List[str] = json.loads(notes)
    content = []

    for i, photo in enumerate(photos):
        img_bytes = await photo.read()
        img_b64 = base64.b64encode(img_bytes).decode()
        filename = photo.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpeg"
        mime = MIME_MAP.get(ext, "image/jpeg")

        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
        })

        note = notes_list[i].strip() if i < len(notes_list) else ""
        if note:
            content.append({"type": "text", "text": f"（第{i+1}张备注：{note}）"})

    content.append({
        "type": "text",
        "text": build_prompt(style, len(photos), style_brief),
    })

    # Step 3: 调用 qwen-vl-max 生成叙事
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen-vl-max",
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 800,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"AI 服务异常: {resp.text[:200]}")

    data = resp.json()
    narrative = data["choices"][0]["message"]["content"]
    return {"ok": True, "narrative": narrative}


@app.get("/api/health")
async def health():
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
