---
title: "LangChain × Ollamaでバグチケット分析AIを構築する — LCEL・構造化出力・バッチ処理の検証"
emoji: "🦜"
type: "tech"
topics: ["langchain", "ollama", "python", "llm", "pydantic"]
published: false
---

## 今回検証したこと

バグチケットの本文を入力し、カテゴリ・重要度・原因候補・推奨対応を返す処理を、LangChainとOllamaで実装した。

`ChatOllama`による呼び出しから始め、`ChatPromptTemplate`、`JsonOutputParser`、LCELによる合成、`batch()`による複数入力の処理までを5段階で確認した。本記事は既存の`langchain-ticket-agent`（コミット`fadd8c4`）を基にした技術検証記録である。プロジェクト名にはagentとあるが、今回の実装はツール選択や自律的な反復を行わない、プロンプト→モデル→パーサーの固定チェーンである。

※　記事の構成・文章整理にはAIを利用し、掲載コードと実行結果を確認しています

## 検証環境

| 要素 | 構成・役割 |
| --- | --- |
| クライアント | Mac、Python 3.14.4、仮想環境 `.venv` |
| 推論サーバー | NUC、Ubuntu Server |
| GPU | NVIDIA GeForce RTX 3070 Ti |
| 推論ランタイム | Ollama 0.35.0 |
| モデル | `qwen3:8b` |
| LangChain Core | `langchain-core==1.6.9` |
| Ollama連携 | `langchain-ollama==1.1.0` |
| スキーマ定義 | `pydantic==2.14.0` |
| Ollama Pythonクライアント | `ollama==0.6.3` |

Mac側でPythonを実行し、LAN経由でNUC側のOllama APIに問い合わせる構成である。NUC・Ubuntu Server・GPUの構成は利用環境の申告に基づく。今回の確認ではOllama APIのバージョンと稼働モデルを取得し、`qwen3:8b`の`size_vram`がモデルサイズと同じ値であることを確認した。ただし、これだけでGPU機種や推論速度を検証したことにはならない。Ubuntuの詳細バージョン、ドライバー、量子化方式、モデルのdigestは未記録である。

```text
Mac / Python 3.14
  ChatPromptTemplate → ChatOllama ── LAN ──> NUC / Ubuntu Server
                         ↑                  Ollama / qwen3:8b
                         └──── 応答 ──────── RTX 3070 Ti
                              ↓
                       JsonOutputParser
                              ↓
                          Python dict
```

### 再現用の準備

既存の仮想環境で確認したバージョンに合わせる例を示す。Python 3.14.4が導入済みであることを前提とする。

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install langchain-core==1.6.9 langchain-ollama==1.1.0 pydantic==2.14.0 ollama==0.6.3
```

これは確認した主要パッケージの一覧であり、推移依存関係まで固定したロックファイルではない。長期的な再現には依存関係の固定とモデルdigestの記録も必要になる。

サーバー側に`qwen3:8b`を用意し、MacからOllama APIに到達できる状態にする。接続先は実際の環境に合わせて設定する。

```bash
# NUC側（モデルがまだない場合）
ollama pull qwen3:8b

# Mac側。以下のホスト名は説明用のプレースホルダー
export OLLAMA_BASE_URL="http://YOUR_OLLAMA_HOST:11434"
```

実行前に上記の`export`で設定する。`.env.example`は設定項目の見本であり、スクリプトが`.env`を自動で読み込む実装にはしていない。未設定の場合は`KeyError: 'OLLAMA_BASE_URL'`で停止する。

## 5段階で実装を確認する

| ファイル | 確認した内容 |
| --- | --- |
| `step01_chat.py` | `ChatOllama.invoke()`で質問し、`response.content`を表示 |
| `step02_prompt.py` | system/humanメッセージと`{ticket}`変数を定義 |
| `step03_parser.py` | 出力スキーマとJSON変換を追加 |
| `step04_chain.py` | `prompt | llm | parser`で合成 |
| `step05_batch.py` | BUG-001〜003を`batch()`で実行 |

### ChatOllama：モデル呼び出し

`ChatOllama`は`langchain-ollama`パッケージから利用する。`model`と`base_url`を指定し、`invoke()`でメッセージを送る。セットアップ方法は[公式のChatOllamaドキュメント](https://docs.langchain.com/oss/python/integrations/chat/ollama)を参照できる。

```python
import os
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="qwen3:8b",
    base_url=os.environ["OLLAMA_BASE_URL"],
    temperature=0,
)
response = llm.invoke(
    "ソフトウェア開発におけるバグチケットとは何か、簡潔に説明してください。"
)
print(response.content)
```

`temperature=0`は出力のばらつきを抑える設定として用いている。これだけで、モデルや推論環境が変わっても完全に同じ結果が得られるとは扱わない。

### ChatPromptTemplate：役割と入力を分ける

systemメッセージには「ソフトウェア品質管理の専門家」という役割、分析項目、原因が確定していない場合の扱いを書く。humanメッセージにはチケット本文を渡す。

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", """
あなたはソフトウェア品質管理の専門家です。
バグチケットを分析してください。
原因が特定できない場合は、推測として扱ってください。
必ず以下のJSON形式で回答してください。
{format_instructions}
"""),
    ("human", "{ticket}"),
])
```

`{ticket}`と`{format_instructions}`はテンプレート変数である。出力形式の説明は`parser.get_format_instructions()`で生成し、入力辞書から渡している。本文を変えても、共通の指示と形式を維持できる。

### JsonOutputParser：スキーマ提示とJSON変換

出力として必要な項目をPydanticモデルに定義する。

```python
from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser

class BugAnalysis(BaseModel):
    category: str = Field(description="バグのカテゴリ")
    severity: Literal["Critical", "High", "Medium", "Low"]
    possible_causes: list[str] = Field(description="考えられる原因")
    recommendations: list[str] = Field(description="推奨する対応方法")

parser = JsonOutputParser(pydantic_object=BugAnalysis)
```

コードでは`ChatOllama(format="json")`も設定する。モデル側のJSON出力指定、プロンプト側のスキーマ説明、受信側のJSONパースという3つの役割を組み合わせている。

ただし、**この`JsonOutputParser`の戻り値はPydanticモデルではなく、今回の出力ではPythonの辞書である。`pydantic_object`を指定しただけで、`severity`の値や必須項目が厳密に検証されるわけではない。** 確認した`langchain-core 1.6.9`の実装でも、`parse_result()`はJSONを読み取る処理で、`BugAnalysis.model_validate()`を呼び出していない。

### LCEL：3つの処理を合成する

```python
chain = prompt | llm | parser
result = chain.invoke({
    "ticket": ticket,
    "format_instructions": parser.get_format_instructions(),
})
```

LCELの`|`で、前段の出力を次段の入力に接続する。

| 段階 | 入力 → 出力 |
| --- | --- |
| prompt | 入力辞書 → ChatPromptValue |
| llm | プロンプト → AIMessage |
| parser | モデル応答 → JSONを読み取ったPythonオブジェクト |

`step03_parser.py`では各段階の`invoke()`を個別に呼び出していた。`step04_chain.py`では同じ流れを合成し、チェーン全体に対して`invoke()`を呼んでいる。合成後も共通のRunnableインターフェースを使えるため、次の`batch()`へ自然に進める。

## batch()：3件のチケットを処理する

以下は`step05_batch.py`の掲載用コードである。接続先を環境変数に置き換えた以外は、入力・プロンプト・モデル設定・並列数・結果表示を既存実装に合わせている。

```python
import os
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Literal


# 出力データの構造を定義
class BugAnalysis(BaseModel):
    category: str = Field(description="バグのカテゴリ")
    severity: Literal["Critical", "High", "Medium", "Low"]
    possible_causes: list[str] = Field(description="考えられる原因")
    recommendations: list[str] = Field(description="推奨する対応方法")


# LLM
llm = ChatOllama(
    model="qwen3:8b",
    base_url=os.environ["OLLAMA_BASE_URL"],
    temperature=0,
    format="json",
)

# OutputParser
parser = JsonOutputParser(pydantic_object=BugAnalysis)

# プロンプト
prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
あなたはソフトウェア品質管理の専門家です。

バグチケットを分析してください。
原因が特定できない場合は、推測として扱ってください。

必ず以下のJSON形式で回答してください。

{format_instructions}
"""
    ),
    ("human", "{ticket}")
])

# バグチケット
tickets = [
    {
        "id": "BUG-001",
        "text": """
ログイン画面で正しいIDとパスワードを入力しても500エラー。
本番環境で全ユーザーに発生。
"""
    },
    {
        "id": "BUG-002",
        "text": """
商品一覧画面の表示に15秒以上かかる。
商品数が1000件を超えると発生。
"""
    },
    {
        "id": "BUG-003",
        "text": """
スマートフォンで購入ボタンが画面外にはみ出す。
PCでは正常に表示される。
"""
    }
]

# LCELでChainを構築
chain = prompt | llm | parser

# 複数の入力を作成
inputs = [
    {
        "ticket": ticket["text"],
        "format_instructions": parser.get_format_instructions()
    }
    for ticket in tickets
]

# 一括実行
results = chain.batch(
    inputs,
    config={"max_concurrency": 1}
)

# 結果表示
for ticket, result in zip(tickets, results):
    print(f"\n===== {ticket['id']} =====")
    print("カテゴリ:", result["category"])
    print("重要度:", result["severity"])

    print("\n原因候補:")
    for cause in result["possible_causes"]:
        print("-", cause)

    print("\n推奨対応:")
    for recommendation in result["recommendations"]:
        print("-", recommendation)

```

`batch()`には入力辞書のリストを渡す。結果は入力の順序に対応するリストとして返るため、`zip(tickets, results)`でチケットIDと結び付けて表示する。

今回は`config={"max_concurrency": 1}`を指定している。複数件をまとめて呼び出しているが、同時に複数のモデル呼び出しを走らせる設定ではない。また、LangChainの`batch()`を使うことと、推論サーバーが複数入力を単一のGPUバッチとして処理することは別である。[RunnableSequenceのAPIリファレンス](https://reference.langchain.com/python/langchain-core/runnables/base/RunnableSequence)も参照されたい。

## BUG-001〜003の実行結果

`step05_batch.py`を仮想環境から実行した。プロセスは終了コード0で完了し、標準エラー出力は空だった。

| ID | 入力の概要 | 出力カテゴリ | 出力重要度 |
| --- | --- | --- | --- |
| BUG-001 | 本番環境で全ユーザーのログインが500エラー | Server-Side | Critical |
| BUG-002 | 商品1000件超で一覧の表示に15秒以上 | Performance Issue | High |
| BUG-003 | スマートフォンで購入ボタンが画面外へはみ出す | UI/UX | High |

```text
===== BUG-001 =====
カテゴリ: Server-Side
重要度: Critical

原因候補:
- サーバー側のエラーサービス（例：認証処理中のNullPointerException）
- データベース接続エラー（例：接続失敗や不正なクエリ）
- 最近のコードデプロイメントで導入されたバグ
- セッション管理の不具合（例：セッションが破損している）

推奨対応:
- サーバーのスタックトレースを確認し、具体的なエラー原因を特定
- 最近のコード変更をロールバックし、問題が再現するか確認
- データベース接続の状態を検証し、接続プールやクエリを確認
- 認証処理のロギングを強化し、エラー発生時の詳細な情報を取得
- セッション管理のロジックを再評価し、不正なセッションの処理を検証

===== BUG-002 =====
カテゴリ: Performance Issue
重要度: High

原因候補:
- 後端サーバーが大量の商品データを取得する際の効率的なクエリ処理が不足している
- フロントエンドで一括取得された大量データのレンダリング処理が重い
- データベースのインデックス不足による検索遅延
- ネットワーク通信での大容量データ転送の遅延

推奨対応:
- ページネーションの実装で大規模データを分ページ取得するように変更
- クエリのパフォーマンスチューニングとインデックス最適化を実施
- フロントエンドでのデータレンダリングを効率化するためのバーチャルスクロール実装
- APIレスポンスの圧縮設定を確認し、通信効率を向上させる
- 負荷テストで大規模データ取得時のシステム性能を検証

===== BUG-003 =====
カテゴリ: UI/UX
重要度: High

原因候補:
- レスポンシブデザインの不備（PCとスマートフォンの表示差異）
- ボタンの幅が固定ピクセルで設定されている
- 絶対位置指定（position: absolute）が正しく制限されていない
- コンテナ要素のoverflowプロパティが画面外の要素を隠している

推奨対応:
- スマートフォン用のメディアクエリを厳密に確認し、表示を調整
- ボタンの幅を相対単位（%、vw/vh）に変更
- 絶対位置指定の要素に親要素の境界を明示的に設定（例: position: relative）
- ブラウザのデバッグツールでスマートフォンシミュレーションを実施
- viewportメタタグの設定を確認し、適切な表示を確保
```

3件ともカテゴリ・重要度・原因候補・推奨対応が表示された。ただし、これは3件で処理が完了したという観測であり、分類精度や原因推定の正しさを証明するものではない。

BUG-001では、全ユーザーが本番環境でログインできないという情報に対してCriticalが返った。原因候補にはNullPointerExceptionが挙がっているが、チケットに実装言語やスタックトレースはなく、その例外が実際に発生した証拠はない。「サーバー側のエラーサービス」という不自然な表現もそのまま残した。ロールバックも実施した操作ではなくモデルの提案であり、変更履歴や復旧手順に照らして判断する必要がある。

BUG-002ではDB・フロントエンド・ネットワークにまたがる候補が返った。切り分けの観点として使えるが、計測値がないのでどこがボトルネックかは判断できない。

BUG-003はUI/UXに分類され、重要度はHighだった。購入操作に影響する可能性を持つ一方、どの端末・画面幅・操作条件で発生するかが不足している。LLMの判定を期待値として固定する前に、業務上の基準と追加情報を用意したい。


## 技術的な考察

### JSON形式と業務上の正しさを分けて検証する

JSONとして読めても、必須キーが欠けていたり、重要度が定義外の値だったりする可能性がある。既存コードは`result["category"]`などを直接参照するため、欠損があると表示段階でも失敗する。

改善するなら、パース後に明示的に検証する。

```python
# 改善案：既存実装には未導入
validated = BugAnalysis.model_validate(result)
print(validated.severity)
```

あるいは`PydanticOutputParser(pydantic_object=BugAnalysis)`へ置き換える。確認したバージョンの`PydanticOutputParser`は`model_validate()`を呼び出す。ただし戻り値がモデルになるため、表示も辞書のキー参照から属性参照に変更する。さらに、型が正しいことと原因推定が正しいことは別なので、ログや再現確認による裏付けは必要である。

### 重要度の基準がまだ定義されていない

現在のプロンプトは4つの重要度を指定するが、「本番環境で全ユーザーがログインできない」「商品一覧の表示が15秒かかる」「スマートフォンで購入できない」をどう評価するか、業務上の基準を定義していない。

特にBUG-003は見た目の問題に見えても、購入操作を妨げるなら影響は大きい。見た目のカテゴリだけで重要度を決めず、操作可否・影響ユーザー・代替手段・売上への影響を追加情報として渡したい。最終判断は、チームで合意した基準と人のレビューに合わせる。

### 原因候補は調査の入口として使う

原因を推測として扱う指示はあるが、出力スキーマには根拠や確信度を入れていない。DBやCSSなどの候補が出ても、入力文だけでは原因を確定できない。次の段階では「確認済みの事実」「仮説」「次に確認するログや手順」を分け、仮説を事実として扱わない出力にしたい。

### 並列数を増やす前に測定する

今回は`max_concurrency=1`で動作を確認した。並列数2以上との比較、ウォームアップ前後の比較、GPU使用率、トークン数、処理時間の計測は行っていない。そのため、スループット改善やRTX 3070 Tiでの最適な並列数は結論付けない。

並列数を変える場合は、同じ入力で待ち時間・エラー率・メモリ使用量を比較する。推論サーバー側の処理能力によっては、同時呼び出しを増やしても待ち行列が増えるだけの場合がある。

### 失敗時の処理は次の課題

既存コードには、タイムアウトの明示指定、失敗したチケットだけの再試行、結果の保存、例外を受け取って継続する処理がない。`batch()`の既定では例外が呼び出し元へ伝播する。

運用するなら`return_exceptions=True`で成功と失敗を分け、IDと結果を保存するなどの対応を加える。ただし、表示ループも例外を扱う形に変更する必要がある。これらは改善案であり、今回の実装で検証済みの機能ではない。

## 次のSTEP：LangSmithでトレースと評価を行う

次はLangSmithを使い、プロンプト→モデル→パーサーの各段階の入出力、所要時間、失敗箇所を追えるようにする。今回の3件を評価用データの出発点にして、重要度の基準を定めたうえでケースを増やす。

比較したい項目は、スキーマ検証の成功率、重要度の期待値との一致、原因の断定を避けられているか、推奨対応が実行可能か、処理時間である。3件だけでは精度の一般化はできないため、性能問題・画面問題・障害の異なるケースと境界条件を追加する。

LangChainのトレース設定は[LangSmith公式クイックスタート](https://docs.langchain.com/langsmith/observability-quickstart)に従う。例えば`LANGSMITH_TRACING=true`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`を設定して実行する。今回はLangSmithへの送信や評価は行っていない。

ローカルモデルを使っていても、外部のLangSmithにトレースを送る設定では入力・出力が送信対象になる。まず架空のチケットだけを使い、実データを扱う際は個人情報・認証情報・内部接続先を除去する。キーの値は記事にもGitにも含めない。

## 今回の到達点

既存コードで、テンプレート化した入力を`qwen3:8b`へ送り、JSONをPythonの辞書に変換し、3件を`batch()`で処理する流れを確認した。LCELによって段階的な実装を一つのチェーンへ整理できた一方で、厳密なスキーマ検証、重要度の評価基準、失敗時の扱い、性能測定は追加の検証が必要である。

## Zennでの管理と公開

この記事はプロジェクト内の`docs/zenn/01-langchain-ollama.md`で管理する。Zenn CLI／GitHub連携で公開する場合は、Zenn用リポジトリの`articles/01-langchain-ollama.md`へ配置する。`docs/zenn/`に保存するだけではZennの公開対象にはならない。

frontmatterは`type: tech`、トピック5件、`published: false`としている。公開前に記事をプレビューし、内容を確認してから公開設定を変更する。[Zenn公式CLIガイド](https://zenn.dev/zenn/articles/zenn-cli-guide)に管理方法がまとまっている。
