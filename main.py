# -*- coding: utf-8 -*-
"""pmj-hosei-imges : 画像補正 API (Cloud Run)

  zaiTask 編集画面の帳票画像を OpenAI に渡して補正する。
  サーバ(149/test1)の負荷を上げないよう、重い処理はすべてここで行う。

      zaiTask(.do) → pmj-door(-real) → [このサービス] → OpenAI

  エンドポイント:
    GET  /        … ヘルスチェック
    POST /hosei   … 画像を補正して返す
    POST /ping    … OpenAI に実際に繋がるかの確認(モデル一覧を1件取得)

  POST /hosei の入力:
    {
      "image_base64": "…",          # 必須。data URI 形式も可
      "prompt":       "…",          # 任意。省略時は既定の補正プロンプト
      "size":         "auto",       # 任意。auto / 1024x1024 / 1024x1536 / 1536x1024
      "model":        "gpt-image-1" # 任意
    }
  返り値:
    { "status":"OK", "image_base64":"…", "mime":"image/png",
      "model":"…", "size":"…", "elapsed":12.3 }

  環境変数 (Cloud Run に設定):
    OPENAI_API_KEY   … 必須
    HOSEI_MODEL      … 任意。既定 gpt-image-1
    HOSEI_SIZE       … 任意。既定 auto
    HOSEI_TIMEOUT    … 任意。既定 600(秒)
    HOSEI_MAX_MB     … 任意。入力画像の上限MB。既定 20
"""

import base64
import binascii
import io
import os
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

DEFAULT_MODEL = os.environ.get("HOSEI_MODEL", "gpt-image-1")
DEFAULT_SIZE = os.environ.get("HOSEI_SIZE", "auto")
TIMEOUT = float(os.environ.get("HOSEI_TIMEOUT", "600"))
MAX_BYTES = int(float(os.environ.get("HOSEI_MAX_MB", "20")) * 1024 * 1024)

# 既定の補正プロンプト。画面側から prompt を渡せば差し替えられる。
DEFAULT_PROMPT = (
    "この画像の余計な線を消してください\n"
    "この画像を斜めにしないでください\n"
    "この画像を文字を読みやすくしてください"
)

ALLOWED_SIZES = ("auto", "1024x1024", "1024x1536", "1536x1024")


def _client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY 未設定")
    return OpenAI(api_key=key, timeout=TIMEOUT)


def _decode_image(value):
    """base64(または data URI)を生バイトに戻す。戻り値は (bytes, mime)。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("image_base64 が空です")
    s = value.strip()
    mime = "image/png"
    if s.startswith("data:"):
        head, _, body = s.partition(",")
        if not body:
            raise ValueError("data URI の形式が不正です")
        if ";" in head and head.startswith("data:"):
            mime = head[5:].split(";")[0] or mime
        s = body
    s = "".join(s.split())            # 改行や空白を除去
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("base64 を復号できません")
    if not raw:
        raise ValueError("画像が空です")
    if len(raw) > MAX_BYTES:
        raise ValueError("画像が大きすぎます (%.1f MB)" % (len(raw) / 1048576.0))
    # 先頭バイトから形式を判定(data URI が無い場合の保険)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    return raw, mime


@app.get("/")
def health():
    return jsonify({
        "status": "ok",
        "service": "pmj-hosei-imges-real",
        "model": DEFAULT_MODEL,
        "size": DEFAULT_SIZE,
        "api_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
    })


@app.post("/ping")
def ping():
    """OpenAI まで届くかの確認。画像は送らない(課金されない)。"""
    try:
        client = _client()
        ids = [m.id for m in client.models.list().data]
    except Exception as e:
        return jsonify({"status": "NG", "error": str(e)[:300]}), 502
    return jsonify({"status": "OK", "model_count": len(ids),
                    "has_default_model": DEFAULT_MODEL in ids})


@app.post("/hosei")
def hosei():
    body = request.get_json(silent=True) or {}

    try:
        raw, mime = _decode_image(body.get("image_base64"))
    except ValueError as e:
        return jsonify({"status": "NG", "error": str(e)}), 400

    prompt = str(body.get("prompt") or DEFAULT_PROMPT)
    model = str(body.get("model") or DEFAULT_MODEL)
    size = str(body.get("size") or DEFAULT_SIZE)
    if size not in ALLOWED_SIZES:
        return jsonify({"status": "NG",
                        "error": "size は %s のいずれかです" % " / ".join(ALLOWED_SIZES)}), 400

    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
    fileobj = io.BytesIO(raw)
    fileobj.name = "page." + ext            # SDK が拡張子から形式を判断するため必要

    t0 = time.time()
    try:
        client = _client()
        res = client.images.edit(
            model=model,
            image=fileobj,
            prompt=prompt,
            size=size,
        )
    except Exception as e:
        return jsonify({"status": "NG", "error": str(e)[:500],
                        "model": model, "size": size}), 502
    elapsed = round(time.time() - t0, 1)

    data = getattr(res, "data", None)
    if not data:
        return jsonify({"status": "NG", "error": "画像が返りませんでした"}), 502

    out_b64 = getattr(data[0], "b64_json", None)
    if not out_b64:
        # 稀に URL で返る実装・設定のための保険
        url = getattr(data[0], "url", None)
        if not url:
            return jsonify({"status": "NG", "error": "画像データが空です"}), 502
        import requests
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        out_b64 = base64.b64encode(r.content).decode("ascii")

    return jsonify({
        "status": "OK",
        "image_base64": out_b64,
        "mime": "image/png",          # gpt-image-1 の出力は PNG
        "model": model,
        "size": size,
        "in_bytes": len(raw),
        "out_bytes": len(out_b64) * 3 // 4,
        "elapsed": elapsed,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
