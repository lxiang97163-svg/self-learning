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


@app.post("/api/generate")
async def generate(
    photos: List[UploadFile] = File(...),
    notes: str = Form("[]"),
    style: str = Form("healing"),
):
    if len(photos) > 20:
        raise HTTPException(status_code=400, detail="最多上传20张照片")

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API key 未配置")

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

    style_name, style_desc = STYLES.get(style, STYLES["healing"])
    content.append({
        "type": "text",
        "text": (
            f"请根据以上{len(photos)}张照片，用{style_name}写一段日记式的叙事记录。\n\n"
            f"要求：\n"
            f"- 风格：{style_desc}\n"
            f"- 字数：200-400字\n"
            f"- 以第一人称书写，像是在回忆这段经历\n"
            f"- 照片有备注的，请结合备注内容准确描述，备注优先于视觉判断\n"
            f"- 不要逐一描述每张照片，融合成一段有起伏的叙事\n"
            f"- 不要出现"照片"、"图片"等词汇，就像真实的亲历者在回忆"
        ),
    })

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
