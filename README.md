# CluMP Simulator

![Status](https://img.shields.io/badge/Status-Production_Ready-green)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![License](https://img.shields.io/badge/License-Research-lightgrey)
![Features](https://img.shields.io/badge/Features-Interactive_Config-orange)
![Visualization](https://img.shields.io/badge/Visualization-Full_Support-purple)

## 概要

このプロジェクトは、CluMP (CLUstered Markov-chain Prefetching) 論文に基づいて実装されたストレージI/Oプリフェッチシミュレータです。論文の実験条件を忠実に再現し、さらにインタラクティブなパラメータ設定機能と包括的な可視化機能を提供します。

**論文**: "CluMP: Clustered Markov Chain#### 実行が遅い
- `n_events`（アクセス数）を減らす
- `cache_size`を小さくする

## 🤝 貢献とサポートェクト全体構成

```
python-clump-simulator/
├── 🆕 clump_config_tool.py          # インタラクティブ設定ツール
├── clump_simulator.py              # 論文準拠基本実装
├── clump_simulator_enhanced.py     # 強化版実装  
├── performance_evaluation.py       # 包括的性能評価
├── visualization.py                # 可視化・レポート生成
├── README.md                       # プロジェクト説明（このファイル）
├── REQUIREMENTS_DEFINITION.md      # 要件定義書
├── TERMINOLOGY_GUIDE.md            # 用語ガイド
└── visualization_output/           # 実行結果・レポート
    └── session_YYYYMMDD_HHMMSS/    # セッション別結果
        ├── comprehensive_report.html
        ├── parameter_heatmaps/
        ├── hit_rate_progression/
        └── baseline_comparison/
```

## 🏆 成果と特徴

### 実装の特徴
- **🎯 完全論文準拠**: Section 3.2-3.3の設計を忠実に実装
- **🚀 動的学習**: オンライン遷移頻度更新
- **💾 メモリ効率**: スパースなマルコフ連鎖表現
- **📊 ベースライン比較**: Linux ReadAheadとの性能比較
- **📈 詳細統計**: プリフェッチ効率、ヒット率、メモリ使用量追跡
- **🎨 包括的可視化**: パラメータ分析、比較チャート、HTMLレポート
- **⚙️ インタラクティブ設定**: ガイド付きパラメータ調整

### 論文との対応
| 論文Section | 実装ファイル | 実装内容 |
|-------------|-------------|----------|
| Section 3.2 | `clump_simulator.py` | チャンク・クラスタ管理 |
| Section 3.3 | `clump_simulator.py` | 8ステップアルゴリズム |
| Section 4.1 | `performance_evaluation.py` | ワークロード実験 |
| Section 4.2 | `performance_evaluation.py` | 性能比較評価 |

## 📚 参考資料

- **論文**: "CluMP: Clustered Markov Chain for Storage I/O Prefetch"
- **著者**: Sungmin Jung, Hyeonmyeong Lee, Heeseung Jo
- **実装仕様**: `REQUIREMENTS_DEFINITION.md`参照
- **用語解説**: `TERMINOLOGY_GUIDE.md`参照

## 🤝 貢献とライセンス

このプロジェクトは研究・教育目的で開発されています。
改善提案や機能追加のご提案をお待ちしています。

---

**CluMP Simulator** - 論文準拠ストレージI/O最適化シミュレータ 🚀✨ch" by Sungmin Jung, Hyeonmyeong Lee, Heeseung Jo

## 🚀 主要機能

### ✨ **新機能** - インタラクティブパラメータ設定
- **設定プリセット**: 論文準拠、高性能、メモリ効率など5種類のプリセット
- **パラメータカスタマイズ**: チャンクサイズ、クラスタサイズ、キャッシュサイズ等を自由に調整
- **設定検証**: パラメータの妥当性チェックと最適化提案
- **コマンドライン対応**: スクリプト実行やバッチ処理に対応
- **設定保存/読み込み**: JSON形式での設定ファイル管理

### 📊 完全論文準拠の核心実装

#### MCRow構造（Section 3.3準拠）
- **CN1-CN3**: 次チャンク候補（確率順）
- **P1-P3**: 対応する遷移頻度
- **動的ソート**: 頻度順、同値なら最新更新優先
- **CN3のバッファ機能**: ソート処理用の一時領域

#### 8ステップアルゴリズム（Section 3.3準拠）
1. ディスクI/O読み取り操作要求
2. メモリ存在確認
3. ディスク読み取り要求（ミス時）
4. データ取得・メモリ読み込み
5. 既存MC存在確認
6. MC情報更新
7. CN1ベースプリフェッチ実行
8. 新MC作成（存在しない場合）

#### チャンク・クラスタ管理（Section 3.2準拠）
- **チャンク**: ディスクブロックのセット（CH_sizeブロック）
- **クラスタ**: MCフラグメントのセット（CL_sizeチャンク）
- **動的割り当て**: 必要時のみメモリ使用（オンデマンド）
- **メモリ計算式**: Mem_required = CL_total × 24B × CL_size

### 🔧 実装の特徴
- **完全論文準拠**: Section 3.2-3.3の設計を忠実に実装
- **動的学習**: オンライン遷移頻度更新
- **メモリ効率**: スパースなマルコフ連鎖表現
- **ベースライン比較**: Linux ReadAheadとの性能比較
- **詳細統計**: プリフェッチ効率、ヒット率、メモリ使用量追跡
- **包括的可視化**: パラメータ分析、比較チャート、HTMLレポート

---

## 📦 インストールと環境構築

### 必要環境
- Python 3.8以上
- pip（パッケージ管理）

### 基本インストール
```bash
git clone <repository-url>
cd python-clump-simulator
```

### 依存関係インストール
```bash
# 基本機能のみ
# 追加依存関係は不要

# 可視化機能を使用する場合
pip install matplotlib numpy seaborn
```

### 3. 動作確認

```bash
python clump_simulator.py
```

## ⚡ クイックスタート

### 🎯 新機能 - インタラクティブパラメータ設定

**最も簡単な方法**: インタラクティブモードで設定
```bash
python clump_config_tool.py
# または
python clump_config_tool.py --interactive
```

**プリセットを使用**:
```bash
# 論文準拠設定
python clump_config_tool.py --preset paper_compliant

# 高性能設定
python clump_config_tool.py --preset high_performance

# メモリ効率設定
python clump_config_tool.py --preset memory_efficient
```

**コマンドラインでカスタム設定**:
```bash
python clump_config_tool.py \
  --chunk-size 16 \
  --cluster-size 128 \
  --cache-size 8192 \
  --prefetch-window 32 \
  --workload kernel
```

### 30秒で体験（従来方式）

```python
from clump_simulator import run_clump_simulation, TraceGenerator

# 1. 合成ワークロード生成
trace = TraceGenerator.generate_synthetic_trace(
    n_events=10000,
    num_files=20, 
    sequential_prob=0.6
)

# 2. CluMPシミュレーション実行（論文準拠）
results = run_clump_simulation(trace=trace)

# 3. 結果確認
print(f"ヒット率: {results['hit_rate']:.3f}")
print(f"プリフェッチ効率: {results['prefetch_efficiency']:.3f}")
```

## 📖 使い方

### 🆕 **推奨**: インタラクティブ設定ツール

#### `clump_config_tool.py` - **NEW!** パラメータ設定・テストツール
**何をするファイル？**
- **5つのプリセット**: 論文準拠、高性能、メモリ効率、小規模、大規模
- **インタラクティブ設定**: ガイド付きパラメータ調整
- **設定検証**: パラメータの妥当性チェックと最適化提案
- **即座にテスト**: 設定後すぐにシミュレーション実行

```bash
# インタラクティブモード（推奨）
python clump_config_tool.py

# プリセット一覧表示
python clump_config_tool.py --list-presets

# 設定保存・読み込み
python clump_config_tool.py --preset high_performance --save-config my_config.json
python clump_config_tool.py --config my_config.json
```

**使う場面:**
- ✅ **初回利用時** - ガイド付きで安心
- ✅ **パラメータ調整** - 効果をすぐに確認
- ✅ **設定の最適化** - 推奨値と警告を表示
- ✅ **バッチ処理** - 設定ファイルで自動化

### 🔍 コアシミュレータファイル

#### `clump_simulator.py` - 論文準拠基本実装
**何をするファイル？**
- 論文Section 3.2-3.3に完全準拠のCluMPアルゴリズム
- **8ステップアルゴリズム**の忠実な実装

```bash
python clump_simulator.py
# → 論文準拠の基本実装で実行（30秒程度）
```

**使う場面:**
- ✅ 論文の正確なアルゴリズムを確認したい
- ✅ 基本性能を測定したい
- ✅ 他の実装との比較基準にしたい

#### `clump_simulator_enhanced.py` - 強化版実装
**何をするファイル？**
- 論文ベースに**適応的学習**機能を追加
- **信頼度ベースプリフェッチ**と**動的窓調整**

```bash
python clump_simulator_enhanced.py
# → 強化版実装で実行（1分程度）
```

**使う場面:**
- ✅ より高性能な予測が欲しい
- ✅ 実用的な改善を試したい
- ✅ 研究用の拡張実装を見たい

#### `performance_evaluation.py` - 総合評価
**何をするファイル？**
- **パラメータスイープ実験**
- **論文との結果比較**
- **Linux ReadAheadベースライン比較**
- **可視化レポート自動生成**

```bash
python performance_evaluation.py
# → 包括的性能評価実行（5-10分）
```

**使う場面:**
- ✅ 包括的な性能分析をしたい
- ✅ 最適パラメータを発見したい
- ✅ 論文結果との比較をしたい
- ✅ 可視化レポートが欲しい

#### `visualization.py` - 可視化・レポート生成
**何をするファイル？**
- **パラメータヒートマップ**
- **ヒット率推移グラフ**
- **ベースライン比較チャート**
- **HTMLレポート生成**

```bash
python visualization.py
# → 各種グラフとHTMLレポート生成
```

### 🚀 実行手順とシナリオ

#### 🎯 **シナリオ1**: 初回利用・パラメータ学習
```bash
# Step 1: インタラクティブツールで設定を学ぶ
python clump_config_tool.py
# → プリセット選択 → パラメータカスタマイズ → すぐに結果確認

# Step 2: 基本実装の動作確認
python clump_simulator.py
# → 論文準拠実装の基本動作を確認

# Step 3: 可視化で結果を理解
python visualization.py
# → グラフとレポートで詳細分析
```

#### 🔬 **シナリオ2**: 研究・実験用途
```bash
# Step 1: 設定を保存してバッチ実行準備
python clump_config_tool.py --preset high_performance --save-config experiment1.json
python clump_config_tool.py --preset memory_efficient --save-config experiment2.json

# Step 2: 設定ファイルでバッチ実行
python clump_config_tool.py --config experiment1.json --no-visualization
python clump_config_tool.py --config experiment2.json --no-visualization

# Step 3: 包括的評価でパラメータ最適化
python performance_evaluation.py
# → 16パターンのパラメータスイープ + 最適化提案
```

#### ⚡ **シナリオ3**: 特定パラメータの効果確認
```bash
# コマンドラインで素早くテスト
python clump_config_tool.py --chunk-size 8 --cluster-size 64 --workload kvm
python clump_config_tool.py --chunk-size 16 --cluster-size 128 --workload kvm
python clump_config_tool.py --chunk-size 32 --cluster-size 256 --workload kvm

# 効果比較: チャンクサイズ 8 vs 16 vs 32
```

### 💡 パラメータ設定ガイド

#### 🔧 重要パラメータの説明

| パラメータ | 説明 | 推奨範囲 | 効果 |
|-----------|------|----------|------|
| **チャンクサイズ** | ディスクブロックをまとめる単位 | 8-32 | 小さい→細かい制御、大きい→効率向上 |
| **クラスタサイズ** | MC管理の分割単位 | 32-128 | 大きい→メモリ効率、小さい→学習精度 |
| **キャッシュサイズ** | メモリキャッシュ容量 | 2048-8192 | 大きい→ヒット率向上、メモリ使用量増加 |
| **プリフェッチ窓** | 一度にプリフェッチするブロック数 | チャンクサイズの1-4倍 | 大きい→積極的、小さい→保守的 |

#### � プリセット詳細

**`paper_compliant`** - 論文準拠設定
```
チャンク: 16, クラスタ: 64, キャッシュ: 4096, 窓: 16
→ 論文実験条件の忠実な再現
```

**`high_performance`** - 高性能設定
```
チャンク: 8, クラスタ: 128, キャッシュ: 8192, 窓: 32
→ 最大のヒット率向上を目指す
```

**`memory_efficient`** - メモリ効率設定
```
チャンク: 32, クラスタ: 32, キャッシュ: 2048, 窓: 8
→ メモリ使用量を最小化
```

**`small_scale`** - 軽量テスト設定
```
チャンク: 4, クラスタ: 16, キャッシュ: 1024, 窓: 4
→ 学習用・デバッグ用
```

**`large_scale`** - 大規模処理設定
```
チャンク: 64, クラスタ: 256, キャッシュ: 16384, 窓: 64
→ 大容量ワークロード対応
```

### 🎨 可視化機能詳細

#### 生成される可視化コンテンツ
python clump_simulator.py
```

1. **パラメータヒートマップ**
   - ヒット率、プリフェッチ効率、メモリ使用量の2D分析
   - チャンクサイズ × クラスタサイズの効果可視化

2. **ヒット率推移グラフ**
   - 時系列でのヒット率変化
   - CluMP vs Linux ReadAheadの比較

3. **ベースライン比較チャート**
   - 複数指標での性能比較
   - 改善効果の定量的評価

4. **包括的HTMLレポート**
   - 全結果の統合レポート
   - インタラクティブな分析機能

### 🔧 高度な使用方法

#### 設定ファイルの活用

**設定保存**:
```bash
# プリセットをカスタマイズして保存
python clump_config_tool.py --preset high_performance --save-config my_config.json

# インタラクティブ設定後に保存
python clump_config_tool.py --interactive --save-config experiment_config.json
```

**設定読み込み**:
```bash
# 保存した設定で実行
python clump_config_tool.py --config my_config.json

# 設定検証のみ
python clump_config_tool.py --config my_config.json --validate-only
```

#### バッチ処理での実験自動化

```bash
# 複数設定の自動実行スクリプト例
for preset in paper_compliant high_performance memory_efficient; do
    python clump_config_tool.py --preset $preset --no-visualization --save-config ${preset}.json
    echo "実験 $preset 完了"
done
```

#### パフォーマンスチューニング

**メモリ使用量を最適化**:
```bash
python clump_config_tool.py \
  --chunk-size 32 \      # 大きなチャンク
  --cluster-size 32 \    # 小さなクラスタ  
  --cache-size 2048 \    # 最小キャッシュ
  --workload small
```

**ヒット率を最大化**:
```bash
python clump_config_tool.py \
  --chunk-size 8 \       # 小さなチャンク
  --cluster-size 128 \   # 大きなクラスタ
  --cache-size 8192 \    # 大きなキャッシュ
  --prefetch-window 32   # 積極的プリフェッチ
```
# 適応的学習機能の動作確認
python clump_simulator_enhanced.py
```

## ⚙️ 設定パラメータ

### 主要パラメータの意味

| パラメータ | 説明 | 効果 | 推奨値 |
|------------|------|------|--------|
| `chunk_size` | チャンクサイズ（ブロック数） | 小さいほど細かい予測、大きいほど単純化 | 8-32 |
| `cluster_size` | クラスタサイズ（チャンク数） | メモリ効率に影響 | 16-64 |
| `cache_size` | キャッシュサイズ（ブロック数） | 大きいほどヒット率向上、メモリ消費増 | 4096 |
| `prefetch_window` | プリフェッチ窓（ブロック数） | 先読み量、大きいほど積極的 | 16-32 |

### パラメータ調整の指針

#### chunk_size（チャンクサイズ）
- **小さい値（4-8）**: ランダムアクセスが多い場合に有効、メモリ使用量多
- **大きい値（16-32）**: 順次アクセスが多い場合に有効、メモリ使用量少

#### cluster_size（クラスタサイズ）  
- **小さい値（16-32）**: 予測精度重視、メモリ使用量多
- **大きい値（64-128）**: メモリ効率重視、予測精度は粗い

## � 評価指標

### 基本指標

#### ヒット率（Hit Rate）
- **意味**: キャッシュにデータが存在した割合
- **計算式**: `ヒット数 / 総アクセス数`
- **目標**: 高いほど良い（通常50-80%）

#### プリフェッチ効率（Prefetch Efficiency）
- **意味**: プリフェッチしたデータが実際に使われた割合
- **計算式**: `使用されたプリフェッチ数 / 総プリフェッチ数`
- **目標**: 高いほど良い（30-70%が一般的）

#### メモリ使用量（MC Rows）
- **意味**: 学習用データ構造（MCRow）の数
- **特徴**: 少ないほどメモリ効率が良い
- **目安**: 数百〜数千程度

### ベースライン比較

#### 比較手法
- **Linux read-ahead相当**: 単純な先読み手法
- **改善率**: CluMPがベースラインより何%良いか

## 📈 実行結果の見方

### `clump_simulator.py`の結果例

```
============================================================
CluMP シミュレーション結果
============================================================
📈 基本統計:
   総アクセス数: 25,000
   キャッシュヒット数: 12,284
   ヒット率: 0.491 (49.1%)

🎯 プリフェッチ統計:
   プリフェッチ総数: 44,456
   プリフェッチ使用数: 6,559
   プリフェッチ効率: 0.148 (14.8%)

💾 メモリ消費:
   MC行数: 1,592
```

### `performance_evaluator.py`の結果例

```
🏆 最適パラメータ発見:
   チャンクサイズ: 16 ブロック
   クラスタサイズ: 16 チャンク
   ヒット率: 0.679 (67.9%)

📈 ベースライン比較:
   CluMP: 67.9%
   単純先読み: 54.3%
   改善率: +25.0%

📁 生成ファイル:
   visualization_output/session_YYYYMMDD_HHMMSS/
   ├── parameter_heatmaps/     # パラメータ比較
   ├── baseline_comparison/    # 手法比較
   └── summary_report.txt     # 詳細レポート
```

### 結果の解釈

#### 🎯 良好な結果の目安
- **ヒット率**: 60%以上
- **プリフェッチ効率**: 40%以上  
- **改善率**: ベースラインより20%以上向上

#### 📊 どちらのファイルを使うべき？

**初めて使う場合:**
1. `clump_simulator.py`でアルゴリズムを理解
2. `performance_evaluator.py`で本格的な分析

**研究・論文作成:**
- `performance_evaluator.py`で全自動分析
- 生成されたグラフをそのまま使用可能

### 可視化出力

可視化機能（matplotlib利用時）では以下が生成されます：

- **ヒット率推移チャート**: 学習効果の確認
- **パラメータヒートマップ**: 最適設定の特定
- **ベースライン比較チャート**: 改善効果の確認

出力先：`visualization_output/session_YYYYMMDD_HHMMSS/`

## � トラブルシューティング

### よくある問題

#### 可視化が表示されない
```bash
pip install matplotlib numpy seaborn
```

#### メモリ不足でエラー
```python
# トレースサイズを小さく設定
trace = TraceGenerator.generate_synthetic_trace(n_events=5000)
```

#### 実行が遅い
- `n_events`（アクセス数）を減らす
- `cache_size`を小さくする

## 📄 ファイル構成

```
python-clump-simulator/
├── clump_simulator.py              # 論文準拠基本実装
├── clump_simulator_enhanced.py     # 強化版実装
├── performance_evaluation.py       # パフォーマンス評価（可視化統合）
├── visualization.py                # 可視化機能
├── REQUIREMENTS_DEFINITION.md      # 要件定義書
├── paper_japanese.md               # 論文日本語翻訳
└── README.md                       # このファイル
```

## 📚 技術詳細

### 論文準拠アルゴリズムの実装

#### 8ステップ処理フロー（Section 3.3）
1. **I/O要求受信**: ディスクブロックアクセス要求
2. **キャッシュ確認**: LRUキャッシュでのヒット/ミス判定
3. **ディスク読み取り**: ミス時の実際のデータ取得
4. **データロード**: メモリキャッシュへの格納
5. **MC存在確認**: 該当チャンクのMCRow存在チェック
6. **MC更新**: 遷移頻度の学習的更新
7. **プリフェッチ**: CN1ベースの予測的先読み
8. **MC作成**: 新チャンク用MCRowの動的生成

#### MCRow動的ソート機能
```python
def sort_by_frequency_then_recency(self):
    """頻度優先、同値なら最新更新優先でソート"""
    entries = [(self.CN1, self.P1), (self.CN2, self.P2), (self.CN3, self.P3)]
    # 頻度降順、同値なら挿入順序で最新優先
    sorted_entries = sorted(entries, key=lambda x: (-x[1], x[0] is None))
    return sorted_entries
```

#### メモリ効率計算
- **MCRow構造**: 24バイト/行（CN1-3: 各4B + P1-3: 各4B）
- **クラスタ管理**: オンデマンド割り当て
- **実メモリ使用量**: active_clusters × cluster_size × 24B

### 実装の特徴
- **完全論文準拠**: Section 3.2-3.3の設計を忠実に実装
- **動的学習**: オンライン遷移頻度更新
- **メモリ効率**: スパースなマルコフ連鎖表現
- **ベースライン比較**: Linux ReadAheadとの性能比較
- **詳細統計**: プリフェッチ効率、ヒット率、メモリ使用量追跡

---

**CluMP Simulator (Paper-Based)** - 学術論文に忠実な研究実装 �✨