# langchain-ticket-agent

LangChainとOllamaでバグチケットを分析する5段階のハンズオンです。

## 接続先の設定

Macから到達できるOllamaサーバーのURLを、同じターミナルで設定してください。
以下のホスト名は説明用のプレースホルダーです。

```bash
source .venv/bin/activate
export OLLAMA_BASE_URL="http://YOUR_OLLAMA_HOST:11434"
python step01_chat.py
python step05_batch.py
```

`step01_chat.py`〜`step05_batch.py`はすべて`OLLAMA_BASE_URL`を参照します。
未設定の場合は`KeyError: 'OLLAMA_BASE_URL'`で停止します。

`.env.example`は設定項目の見本です。スクリプトは`.env`を自動読み込みしません。
接続先は上記の`export`で設定してください。内部IPや認証情報を含む設定ファイルはGitに追加しないでください。

## スクリプト

| ファイル | 内容 |
| --- | --- |
| step01_chat.py | モデル呼び出し |
| step02_prompt.py | プロンプトテンプレート |
| step03_parser.py | JSON出力とパース |
| step04_chain.py | LCELによる合成 |
| step05_batch.py | 複数チケットの処理 |

技術検証記事は[docs/zenn/01-langchain-ollama.md](docs/zenn/01-langchain-ollama.md)にあります。
