# pmj-hosei-imges-real

帳票画像の補正 API (Cloud Run)。OpenAI に画像を渡して補正した画像を返す。

サーバ(149 / test1)の負荷を上げないよう、画像処理はすべてこちらで行う。

```
zaiTask(.do) → pmj-door(-real) → [pmj-hosei-imges] → OpenAI
```

- `pmj-hosei-imges`      … 検証用
- `pmj-hosei-imges-real` … 本番用

## エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET  | `/`      | ヘルスチェック |
| POST | `/ping`  | OpenAI まで届くかの確認(画像は送らない=課金なし) |
| POST | `/hosei` | 画像を補正して返す |

### POST /hosei

```json
{
  "image_base64": "…",
  "prompt": "…",
  "size": "auto",
  "model": "gpt-image-1"
}
```

`image_base64` 以外は省略可。`data:image/jpeg;base64,…` 形式でも受け付ける。

返り値:

```json
{ "status":"OK", "image_base64":"…", "mime":"image/png",
  "model":"gpt-image-1", "size":"auto",
  "in_bytes":312456, "out_bytes":845120, "elapsed":23.4 }
```

既定のプロンプト:

```
この画像の余計な線を消してください
この画像を斜めにしないでください
この画像を文字を読みやすくしてください
```

## 必要な環境変数 (Cloud Run に設定)

| 変数 | 必須 | 説明 |
|---|---|---|
| `OPENAI_API_KEY` | ○ | OpenAI の APIキー |
| `HOSEI_MODEL`    | 任意 | 既定 `gpt-image-1` |
| `HOSEI_SIZE`     | 任意 | 既定 `auto`。`1024x1024` / `1024x1536` / `1536x1024` |
| `HOSEI_TIMEOUT`  | 任意 | OpenAI への待ち時間(秒)。既定 600 |
| `HOSEI_MAX_MB`   | 任意 | 入力画像の上限MB。既定 20 |
| `PORT`           | 自動 | Cloud Run が設定 |

## デプロイ

GitHub への push で自動デプロイされる(リポジトリからの継続的デプロイ)。
`gcloud run deploy` は不要。環境変数の追加・変更だけコンソールで行う。

## pmj-door 側の設定

door は `target` 名で転送先を選ぶため、door のサービスに次を追加する。

| 変数 | 値 |
|---|---|
| `TARGET_HOSEIIMGES` | このサービスの URL |

あわせて、door のサービスアカウントにこのサービスへの `roles/run.invoker` を付与する。

呼び出し方:

```json
POST /call
{ "target": "hoseiimges", "path": "/hosei",
  "payload": { "image_base64": "…" } }
```

## ★ 注意: 画像生成AIによる補正のリスク

このサービスは画像生成モデル(`gpt-image-1`)で画像を**作り直して**いる。
元画像にフィルタをかけているのではなく、**新しい画像を描き起こしている**。

そのため、次の点に注意すること。

- **数字や文字が書き換わる可能性がある**。決算書の金額が別の数字になっても
  見た目は自然なため、気付きにくい。補正後の画像をそのまま OCR の入力に
  使う場合は、**必ず元画像と突き合わせる運用**が必要。
- **解像度が落ちる**。入力が 3311×4680 でも、出力は最大 1536px 程度。
  細かい数字が潰れることがある。
- **縦横比が変わることがある**。A4(縦横比 0.707)に対し、モデルの出力は
  1024×1536(0.667) などに丸められる。

幾何的な補正(傾き・台形)や明るさ・コントラストの調整だけが目的であれば、
OpenCV による決定的な処理のほうが安全・高速・安価で、
文字が書き換わる心配もない(`ana-aiocr-photo` が同じ方式を採用している)。

用途に応じて使い分けること。
