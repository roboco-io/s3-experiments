# S3 Experiments — S3で他に何ができる？

[English](./README.md) | [한국어](./README.ko.md) | **日本語**

> S3が単なるストレージではないとしたら？ S3を**Key-Valueストア**、**イベントストア**、**耐久性RDBMS（Litestream+SQLite）**、**サーバーレスRDBMS（Athena）**、**ファイルI/O代替**として活用する方法を探求します — 動作するコード、CDKデプロイ、専用AWSサービスとの正直なベンチマーク付き。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)
[![AWS CDK](https://img.shields.io/badge/AWS_CDK-v2-orange.svg)](https://aws.amazon.com/cdk/)

## なぜS3なのか？

Amazon S3は「ファイルを置く場所」として見られがちです。しかし、**GBあたり$0.023のストレージ**、**イレブンナイン（99.999999999%）の耐久性**、**管理するサーバーゼロ**、**無限のスケーラビリティ**を備えたS3は、AWSで最も強力なプリミティブの一つです。

このプロジェクトは、S3を従来の役割を超えて活用した場合に何が起こるかを探求します：

| 得られるもの | コスト |
|-------------|--------|
| プロビジョニング済み容量ゼロ | 使った分だけ支払い |
| サーバー、クラスター、パッチなし | IAMポリシー＝セキュリティ設定の全て |
| あらゆる負荷に自動スケーリング | キャパシティプランニング不要 |
| 99.999999999%の耐久性 | 安心して眠れる |

**このプロジェクトは、S3が専用サービスを置き換えると主張するものではありません。** 各パターンには、S3が適切な場合とDynamoDB、RDS、Auroraを使用すべき場合を示す正直なトレードオフ分析が含まれています。

## パターン

| # | パターン | 置き換え対象 | キーインサイト | ステータス |
|---|---------|-------------|--------------|----------|
| 1 | [**Key-Value Store**](./patterns/kv-store/) | DynamoDB | S3オブジェクトキー＝あなたのキー、オブジェクトボディ＝あなたの値。50万キーをコスト効率よく処理できるか？ | 🔲 |
| 2 | [**S3 as Event Store**](./patterns/event-sourcing/) | Kinesis / SQS | S3 Event Notificationsを耐久性のあるリプレイ可能なイベントログとして活用。 | 🔲 |
| 3 | [**Litestream + SQLite**](./patterns/litestream-sqlite/) | RDS（小規模） | インメモリDB速度 + [Litestream](https://github.com/benbjohnson/litestream)によるS3耐久性。Fargate Spot RTO/RPO実験。 | 🔲 |
| 4 | [**Serverless RDBMS**](./patterns/serverless-rdbms/) | RDS / Aurora | S3上のParquet + Athena = データベースサーバーなしでSQLクエリ。数秒を許容できるなら、なぜRDSにコストをかけるのか？ | 🔲 |
| 5 | [**S3 as File I/O**](./patterns/s3-file-io/) | EBS / EFS | S3 APIの読み書きはローカルファイルシステムと比べてどうか？ファイルサイズ別パフォーマンスプロファイリング。 | 🔲 |

各パターンは**独立してデプロイ可能**です — 関心のあるパターンを一つ選んで10分以内にデプロイできます。

## クイックスタート

### 前提条件

- Node.js 20+
- AWS CLI（認証情報設定済み）
- AWS CDK v2（`npm install -g aws-cdk`）

### パターンのデプロイ

```bash
# リポジトリをクローン
git clone https://github.com/roboco-io/s3-experiments.git
cd s3-experiments

# 依存関係をインストール
npm install

# パターンを選択してデプロイ
cd patterns/kv-store
npx cdk deploy

# デモを実行
npx tsx src/demo.ts

# ベンチマークを実行
npm run benchmark

# クリーンアップ（全リソース削除）
npx cdk destroy
```

## プロジェクト構成

```
s3-experiments/
├── README.md                          # English README
├── README.ko.md                       # 한국어 README
├── README.ja.md                       # 日本語 README（現在のドキュメント）
├── patterns/
│   ├── kv-store/                      # パターン1: S3 Key-Value Store
│   │   ├── README.md                  #   アーキテクチャ、使用法、トレードオフ
│   │   ├── lib/                       #   CDKスタック
│   │   ├── src/                       #   デモコード & Lambdaハンドラー
│   │   └── benchmark/                 #   パフォーマンス & コスト比較
│   ├── event-sourcing/                # パターン2: S3 Event Store
│   ├── litestream-sqlite/             # パターン3: Litestream + SQLite + Fargate
│   ├── serverless-rdbms/             # パターン4: S3 + Athena RDBMS
│   └── s3-file-io/                    # パターン5: S3 API vs ファイルシステム
├── shared/                            # 共通ユーティリティ（S3クライアント、コスト計算機）
├── docs/
│   ├── architecture.md                # アーキテクチャ哲学
│   ├── cost-comparison.md             # 統合コスト比較
│   └── when-to-use.md                 # 判断ガイド
└── CONTRIBUTING.md                    # 新パターンの追加方法
```

## ベンチマーク

全てのパターンには、S3ベースの実装と置き換え対象の専用AWSサービスを比較するベンチマークが含まれています。

| パターン | 測定指標 | 比較対象 |
|---------|---------|---------|
| KV Store | レイテンシ（p50/p95/p99）、スループット、コスト/1Mオペレーション（10K〜500Kキー） | DynamoDB on-demand（実測） |
| Event Store | 書き込みレイテンシ、プロジェクション遅延、コスト/1Mイベント | Kinesis Data Streams（公式価格） |
| Litestream+SQLite | RTO、RPO、クエリレイテンシ、月額コスト（On-Demand vs Spot） | RDS db.t4g.micro（実測） |
| Serverless RDBMS | 複雑度別クエリレイテンシ（1MB〜10GB）、スキャンコスト、コスト/1Kクエリ | Aurora Serverless v2（公式価格） |
| S3 File I/O | ファイルサイズ別読み書きレイテンシ（1KB〜1GB）、スループット（MB/s）、同時IOPS | EBS gp3 + EFS（実測） |

**方法論:** メトリクスあたり100回以上反復、最初の10回はウォームアップとして除外、Lambda cold/warmレイテンシを分離報告。全ベンチマークは`us-east-1`で実行。各パターンの`benchmark/results.md`で詳細確認。

## S3パターンの使いどころ

S3ベースのパターンが輝く場合：
- **コスト重視** — 可能な限り低いストレージ/コンピュートコストが必要な場合
- **低〜中トラフィック** — 毎分数百〜数千リクエスト（数百万ではない）
- **シンプルさ** — 管理するインフラがゼロであってほしい場合
- **耐久性 > レイテンシ** — アーカイブ、監査ログ、イベント履歴

専用サービスを使うべき場合：
- **サブミリ秒レイテンシ** — DynamoDB、ElastiCacheはこのために作られている
- **複雑なトランザクション** — 複数オペレーションにまたがるACID保証
- **高頻度読み取り** — S3にはプレフィックスあたりのリクエスト制限がある
- **リアルタイムストリーミング** — Kinesis/SQSがより良い保証を提供

詳細ガイドは[docs/when-to-use.md](./docs/when-to-use.md)を参照してください。

## 技術スタック

- **ランタイム:** Node.js 20+ / TypeScript 5+
- **IaC:** AWS CDK v2
- **AWS SDK:** @aws-sdk/* v3
- **テスト:** Vitest
- **パッケージマネージャー:** npm workspaces

## コントリビュート

コントリビューションを歓迎します！[CONTRIBUTING.md](./CONTRIBUTING.md)で以下の方法を確認してください：
- 新しいS3パターンの追加
- 既存ベンチマークの改善
- ドキュメントの修正

## ライセンス

MIT License。[LICENSE](./LICENSE)を参照してください。

---

**管理する必要のないインフラが最高のインフラである**という信念のもとに構築されました。
