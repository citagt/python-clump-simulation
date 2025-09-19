# CluMP要件定義書

## 1. 概要

本要件定義書は、CluMP (Clustered Markov Chain for Prefetch) 論文の内容に正確に基づいて作成されたCluMPシミュレータの実装要件を定義します。論文のSection 3.2-3.3の設計仕様、Section 4の評価方法、アルゴリズムの動作シーケンスを忠実に再現し、さらに研究・実験を支援するインタラクティブパラメータ設定機能を統合したシステムの仕様を記述します。

## 2. システム概要

### 2.1. 目的と目標

**主要目的**:
- Linux先読みアルゴリズムの限界（逐次アクセスのみ有効、128KB固定窓）を克服
- マルコフ連鎖を用いた非逐次アクセスにも有効なプリフェッチシステムの実現
- チャンク・クラスタ構造によるメモリ効率的なMC管理
- 実際のワークロード（KVM起動、Linuxカーネルビルド）における性能向上の実証

**新機能目標**:
- 研究者・学習者向けのインタラクティブパラメータ設定機能
- 設定プリセットによる用途別最適化
- リアルタイムパフォーマンス予測と最適化提案
- バッチ処理対応とスクリプト自動化支援

### 2.2. システムアーキテクチャ

```
CluMPシステム（統合版）
├── 🆕 パラメータ設定レイヤ
│   ├── インタラクティブUI
│   ├── プリセット管理
│   ├── 設定検証・最適化
│   └── 設定ファイル管理
├── コア算法レイヤ
│   ├── チャンク管理（ディスクブロックのCH_size単位グループ化）
│   ├── クラスタ管理（MCフラグメントのCL_size単位動的割り当て）
│   ├── MCRow管理（CN1-3/P1-3、動的ソート）
│   └── キャッシュシステム（LRU+プリフェッチ統計）
├── 評価・分析レイヤ
│   ├── プリフェッチヒット率測定
│   ├── ミスプリフェッチ分析
│   ├── メモリオーバーヘッド分析
│   └── ベースライン比較
└── 可視化・レポートレイヤ
    ├── パラメータヒートマップ
    ├── 時系列分析
    ├── HTMLレポート生成
    └── インタラクティブダッシュボード
```

### 2.3. 新機能要件

#### 2.3.1. インタラクティブパラメータ設定システム
- **ガイド付き設定UI**: 初心者向けの段階的パラメータ設定
- **リアルタイム検証**: 入力値の妥当性即座チェック
- **最適化提案**: パフォーマンス予測とアドバイス機能
- **設定プリセット**: 論文準拠、高性能、メモリ効率等の事前定義

#### 2.3.2. 高度設定管理
- **設定ファイル**: JSON形式での設定保存・読み込み
- **バッチ処理**: コマンドライン引数での自動実行
- **設定バリデーション**: パラメータ組み合わせの妥当性確認
- **プロファイル管理**: 用途別設定の管理と切り替え

## 3. データ構造仕様

### 3.1. MCRow（マルコフ連鎖行）
論文Section 3.3に基づく6フィールド構造：

```
MCRow {
    CN1: int  // 最も頻繁にアクセスされるチャンク番号
    CN2: int  // 2番目に頻繁にアクセスされるチャンク番号  
    CN3: int  // 最も最近アクセスされたチャンク番号（ソート用バッファ）
    P1: int   // CN1への遷移頻度
    P2: int   // CN2への遷移頻度
    P3: int   // CN3への遷移頻度
}
```

### 3.2. 🆕 パラメータ設定構造
```
CluMPConfiguration {
    // 基本アルゴリズムパラメータ
    chunk_size_blocks: int = 16          // チャンクサイズ（ブロック数）
    cluster_size_chunks: int = 64        // クラスタサイズ（チャンク数）
    cache_size_blocks: int = 4096        // キャッシュサイズ（ブロック数）
    prefetch_window_blocks: int = 16     // プリフェッチ窓サイズ（ブロック数）
    
    // ワークロード設定
    workload_type: str = "kvm"           // ワークロード種類
    workload_size: int = 15000           // ワークロードサイズ
    workload_range: int = 30000          // ブロック範囲
    
    // 実験設定
    enable_comparison: bool = True        // Linux先読みとの比較
    enable_visualization: bool = True     // 結果可視化
    random_seed: int = 42                // 乱数シード
    
    // 詳細設定
    verbose: bool = False                // 詳細ログ出力
    output_dir: str = "./results"        // 結果出力ディレクトリ
}
```

### 3.3. クラスタ管理システム
```
ClusterManager {
    cluster_size: int                    // クラスタサイズ（チャンク数）
    clusters: Dict[int, Dict[int, MCRow]] // cluster_id -> {chunk_id -> MCRow}
    allocated_mc_rows: int               // 割り当て済みMC行数
}
```

**重要な設計原理：**
- 必要時のみ動的割り当て（オンデマンド）
- 実メモリ使用量 << Mem_required
- メモリ計算式：allocated_mc_rows × 24B

### 3.4. キャッシュシステム
```
LRUCache {
    cache_size: int              // キャッシュ容量（ブロック数）
    cache: OrderedDict           // LRU順序管理
    prefetch_stats: {
        prefetch_total: int      // プリフェッチ総数
        prefetch_used: int       // 使用されたプリフェッチ数
        prefetch_unused: int     // 未使用プリフェッチ数
    }
}
```

### 3.5. 🆕 設定プリセット
```
ParameterPresets {
    paper_compliant: CluMPConfiguration    // 論文準拠設定
    high_performance: CluMPConfiguration   // 高性能設定
    memory_efficient: CluMPConfiguration   // メモリ効率設定
    small_scale: CluMPConfiguration        // 小規模テスト設定
    large_scale: CluMPConfiguration        // 大規模処理設定
}
```
- CN1は常に最高確率の次チャンクを保持（プリフェッチ対象）
- P値が等しい場合、最も最近更新されたものが優先
- CN3はソート処理のバッファとして機能
- 各I/Oアクセス毎に動的ソート・更新

### 3.2. チャンク・クラスタ構造
論文Section 3.2の設計：

```
チャンク = ディスクブロックのセット（CH_sizeブロック）
クラスタ = MCフラグメントのセット（CL_sizeチャンク）

計算式：
CH_total = B_total / CH_size
CL_total = CH_total / CL_size  
Mem_required = CL_total × 24B × CL_size
```

**メモリ効率化原理：**
- 全クラスタの事前割り当てなし
- 必要時のみ動的割り当て（オンデマンド）
- 実メモリ使用量 << Mem_required

### 3.3. キャッシュシステム
```
LRUCache {
    cache_size: int              // キャッシュ容量（ブロック数）
    cache: OrderedDict           // LRU順序管理
    prefetch_stats: {
        prefetch_total: int      // プリフェッチ総数
        prefetch_used: int       // 使用されたプリフェッチ数
        prefetch_unused: int     // 未使用プリフェッチ数
    }
}
```

## 4. アルゴリズム仕様

### 4.1. CluMP動作シーケンス（論文Section 3.3）
論文に明記された8ステップ：

```
1. ディスクI/O読み取り操作要求
2. 要求ブロックのメモリ存在確認
   - 存在: MCの確認・更新へ
   - 不存在: ステップ3へ
3. ディスクからの読み取り要求
4. データ取得・メモリ読み込み
5. 既存MC存在確認
6. MC情報更新（または新規作成）
7. CN1基準プリフェッチ実行（プリフェッチ窓サイズ）
8. 新MCの作成（存在しない場合）
```

### 4.2. MC更新アルゴリズム
```python
def update_mc_row(current_chunk, next_chunk):
    """論文準拠のMC更新"""
    
    # 既存チャンクの場合：頻度増加
    if next_chunk in [CN1, CN2, CN3]:
        対応するP値を1増加
        
    # 新チャンクの場合：CN3を置換
    else:
        CN3 = next_chunk
        P3 = 1
    
    # 動的ソート（頻度順、同値なら最新優先）
    sort_by_frequency_then_recency()
    
    # CN1が次回プリフェッチ対象
    return CN1
```

### 4.3. プリフェッチ実行
```python
def execute_prefetch(predicted_chunk, prefetch_window):
    """CN1に基づくプリフェッチ"""
    start_block = predicted_chunk * chunk_size
    for i in range(prefetch_window):
        prefetch_block(start_block + i)
```

### 4.4. 🆕 インタラクティブ設定アルゴリズム

#### 4.4.1. パラメータ検証
```python
def validate_configuration(config):
    """設定パラメータの妥当性検証"""
    errors = []
    warnings = []
    
    # 基本範囲チェック
    if chunk_size <= 0: errors.append("チャンクサイズ > 0")
    if cluster_size <= 0: errors.append("クラスタサイズ > 0")
    if cache_size <= 0: errors.append("キャッシュサイズ > 0")
    if prefetch_window <= 0: errors.append("プリフェッチ窓 > 0")
    
    # 最適性チェック
    if chunk_size > 64: warnings.append("チャンクサイズ大きすぎ")
    if cluster_size > 512: warnings.append("クラスタサイズ大きすぎ")
    if prefetch_window > chunk_size: warnings.append("窓サイズ > チャンクサイズ")
    
    # メモリ使用量予測
    memory_mb = estimate_memory_usage(config)
    if memory_mb > 1000: warnings.append(f"予想メモリ: {memory_mb}MB")
    
    return len(errors) == 0, errors + warnings
```

#### 4.4.2. 最適化提案
```python
def suggest_optimizations(config):
    """最適化提案生成"""
    suggestions = []
    
    # チャンクサイズ最適化
    if chunk_size < 8:
        suggestions.append("チャンクサイズを8-16に増加推奨")
    elif chunk_size > 32:
        suggestions.append("チャンクサイズを16-32に減少推奨")
    
    # クラスタサイズ最適化
    if cluster_size < 32:
        suggestions.append("クラスタサイズを64-128に増加推奨")
    
    # プリフェッチ窓最適化
    optimal_window = chunk_size * 2
    if prefetch_window < optimal_window // 2:
        suggestions.append(f"プリフェッチ窓を{optimal_window}に調整推奨")
    
    return suggestions
```

#### 4.4.3. メモリ使用量予測
```python
def estimate_memory_usage(config):
    """メモリ使用量予測（MB）"""
    # キャッシュメモリ（ブロックあたり8B想定）
    cache_memory = config.cache_size * 8
    
    # MC行メモリ（最大使用想定）
    max_chunks = config.workload_range // config.chunk_size
    max_mc_rows = min(max_chunks, config.workload_size // 10)  # 10%アクティブ想定
    mc_memory = max_mc_rows * 24  # 24B per MC row
    
    total_bytes = cache_memory + mc_memory
    return total_bytes / (1024 * 1024)  # MB換算
```

## 5. Linux先読みベースライン実装

### 5.1. 論文準拠仕様
論文Section 2.1、Section 4での比較条件：

```
LinuxReadAhead {
    初期窓サイズ: 128KB
    最大窓サイズ: 2048KB
    逐次検出: 2ブロック連続
    窓調整: 逐次時倍増、非逐次時リセット
    キャッシュ: LRU管理
}
```

## 6. 🆕 インタラクティブ設定システム要件

### 6.1. ユーザーインターフェース要件

#### 6.1.1. インタラクティブモード
```
実行: python clump_config_tool.py --interactive

フロー:
1. プリセット選択UI
   - 5つのプリセット表示
   - 各プリセットの説明表示
   - カスタマイズ可否選択

2. パラメータカスタマイズUI
   - 基本パラメータ設定（chunk, cluster, cache, window）
   - ワークロード設定（type, size, range）
   - 実験設定（comparison, visualization, verbose）
   - リアルタイム説明・範囲表示

3. 設定検証・提案UI
   - 妥当性チェック結果表示
   - 警告・エラー表示
   - 最適化提案表示
   - メモリ使用量予測表示
```

#### 6.1.2. コマンドライン引数
```
基本実行:
  python clump_config_tool.py [options]

主要オプション:
  --preset {paper_compliant,high_performance,memory_efficient,small_scale,large_scale}
  --chunk-size N          チャンクサイズ設定
  --cluster-size N        クラスタサイズ設定  
  --cache-size N          キャッシュサイズ設定
  --prefetch-window N     プリフェッチ窓設定
  --workload {kvm,kernel,mixed,custom}
  --workload-size N       ワークロードサイズ
  --config FILE           設定ファイル読み込み
  --save-config FILE      設定ファイル保存
  --list-presets          プリセット一覧表示
  --validate-only         検証のみ実行
  --no-comparison         比較実験スキップ
  --no-visualization      可視化スキップ
  --verbose              詳細ログ出力
```

### 6.2. 設定ファイル仕様

#### 6.2.1. JSON形式設定
```json
{
  "chunk_size_blocks": 16,
  "cluster_size_chunks": 64,
  "cache_size_blocks": 4096,
  "prefetch_window_blocks": 16,
  "workload_type": "kvm",
  "workload_size": 15000,
  "workload_range": 30000,
  "enable_comparison": true,
  "enable_visualization": true,
  "random_seed": 42,
  "verbose": false,
  "output_dir": "./results"
}
```

#### 6.2.2. 設定ファイル操作
```
保存: --save-config config.json
読込: --config config.json
検証: --config config.json --validate-only
```

### 6.3. プリセット要件

#### 6.3.1. プリセット定義
```
paper_compliant:
  説明: 論文準拠設定 - 論文の実験条件を再現
  パラメータ: chunk=16, cluster=64, cache=4096, window=16

high_performance:  
  説明: 高性能設定 - 最大のヒット率向上を目指す
  パラメータ: chunk=8, cluster=128, cache=8192, window=32

memory_efficient:
  説明: メモリ効率設定 - メモリ使用量を最小化
  パラメータ: chunk=32, cluster=32, cache=2048, window=8

small_scale:
  説明: 小規模設定 - 軽量テストや学習用
  パラメータ: chunk=4, cluster=16, cache=1024, window=4

large_scale:
  説明: 大規模設定 - 大容量ワークロード対応
  パラメータ: chunk=64, cluster=256, cache=16384, window=64
```

### 6.4. 検証・最適化要件

#### 6.4.1. パラメータ検証
```
必須チェック:
- 全パラメータ > 0
- チャンクサイズ <= 1024
- クラスタサイズ <= 512
- キャッシュサイズ >= 256
- プリフェッチ窓 <= チャンクサイズ * 4

推奨チェック:
- チャンクサイズ 4-64（推奨範囲）
- クラスタサイズ 16-256（推奨範囲）
- キャッシュサイズ >= 1024（推奨最小）
- メモリ使用量 <= 1000MB（推奨上限）
```

#### 6.4.2. 最適化提案
```
チャンクサイズ最適化:
- < 8: "8-16に増加推奨（効率向上）"
- > 32: "16-32に減少推奨（応答性向上）"

クラスタサイズ最適化:
- < 32: "64-128に増加推奨（MC効率向上）"

窓サイズ最適化:
- < chunk_size: "chunk_size * 2推奨"
- > chunk_size * 4: "chunk_size * 2-4推奨"
```

## 7. 評価・実験要件

### 7.1. 論文準拠実験（Section 4）

**KVM起動ワークロード**
```
- サイズ：42.53MB相当
- 特性：VM起動プロセス、混合アクセスパターン
- 期待結果：ヒット率 41.39% → 79.22%（1.91x改善）
```

**Linuxカーネルビルドワークロード**  
```
- サイズ：7.96GB相当（並列ビルド）
- 特性：非連続ブロックアクセス、makeプロセス
- 期待結果：ヒット率 59% → 77.25%（1.31x改善）
```

### 7.2. 🆕 カスタムワークロード要件

#### 7.2.1. ワークロード種類
```
kvm: VM起動パターン（高い逐次性 + ジャンプ）
kernel: カーネルビルドパターン（混合アクセス）
mixed: 50% KVM + 50% Kernel
custom: ユーザー定義パターン
```

#### 7.2.2. ワークロード生成要件
```python
def generate_workload(type, size, range):
    """ワークロード生成仕様"""
    if type == "kvm":
        # Phase 1: ブートローダー（高逐次性）
        # Phase 2: カーネル読み込み（中程度逐次性）
        # Phase 3: システム初期化（混合パターン）
    elif type == "kernel":
        # ソースファイル逐次読み込み
        # ヘッダーファイルランダムアクセス
        # オブジェクトファイル生成
    elif type == "mixed":
        # 50%ずつ混合
    elif type == "custom":
        # 60% 逐次, 20% 小ジャンプ, 20% 大ジャンプ
```
Linux ReadAhead {
    initial_window: 128KB        // 初期プリフェッチ窓
    max_window: configurable     // 最大窓サイズ
    sequential_detection: bool   // 逐次アクセス検出
    window_doubling: bool        // 逐次継続時の窓倍増
    window_reset: bool           // 非逐次時のリセット
}
```

### 5.2. 動作アルゴリズム
```python
def linux_readahead_process(block_id):
    """Linux先読みアルゴリズム（論文準拠）"""
    
    # 逐次性チェック
    if is_sequential(block_id, last_block):
        # 窓サイズ倍増（継続的逐次アクセス）
        if consecutive_sequential > threshold:
            window_size = min(window_size * 2, max_window)
        
        # プリフェッチ実行
        prefetch_sequential(block_id, window_size)
    else:
        # 非逐次：窓リセット、プリフェッチなし
        window_size = 128KB
        # プリフェッチ実行せず
```

## 6. 評価指標仕様

### 6.1. 主要メトリクス（論文Section 4準拠）

**1. プリフェッチヒット率**
```
hit_rate = cache_hits / total_accesses
目標：Linux先読み vs CluMP
- KVM: 41.39% → 79.22% (1.91倍改善)
- カーネルビルド: 59% → 77.25% (1.31倍改善)
```

**2. ミスプリフェッチ率**
```
miss_prefetch_rate = unused_prefetch_blocks / total_prefetch_blocks
目標：Linux先読みより大幅に低減
```

**3. MCメモリオーバーヘッド**
```
memory_overhead = allocated_mc_rows * 24B
メモリ効率性：総ワークロードサイズに対して控えめ
```

### 6.2. パラメータ感度分析
論文Section 4.2-4.4に基づく：

```python
# テスト対象パラメータ範囲
chunk_sizes = [4, 8, 16, 32, 64, 128, 256, 512]  # ブロック
cluster_sizes = [16, 32, 64, 128, 256]           # チャンク
cache_sizes = [1024, 2048, 4096, 8192]          # ブロック
prefetch_windows = [8, 16, 32, 64]              # ブロック

# 評価観点
- ヒット率への影響（チャンクサイズが主要因子）
- ミスプリフェッチへの影響
- メモリ使用量への影響
- 最適パラメータ組み合わせの特定
```

## 7. ワークロード仕様

### 7.1. 実ワークロード模擬（論文Section 4.1）

**KVM起動ワークロード**
```
- サイズ：42.53MB
- 特性：VM起動プロセス、混合アクセスパターン
- 期待結果：ヒット率 41.39% → 79.22%
```

**Linuxカーネルビルドワークロード**  
```
- サイズ：7.96GB（並列ビルド）
- 特性：非連続ブロックアクセス、makeプロセス
- 期待結果：ヒット率 59% → 77.25%
```

### 7.2. 合成ワークロード生成
実ワークロードを模擬する合成トレース：

```python
def generate_kvm_like_workload():
    """KVM起動模擬ワークロード"""
    # 混合パターン：
    # - 40% 逐次アクセス（起動シーケンス）
    # - 35% ランダムアクセス（設定ファイル読み込み）
    # - 25% 小規模ジャンプ（ライブラリロード）

def generate_kernel_build_workload():
    """カーネルビルド模擬ワークロード"""
    # 混合パターン：
    # - 30% 逐次アクセス（ソースファイル読み込み）
    # - 50% ランダムアクセス（ヘッダーファイル）
    # - 20% 大規模ジャンプ（並列コンパイル）
```

## 8. 性能要件

### 8.1. 機能要件
- [必須] 論文の8ステップアルゴリズム完全実装
- [必須] MCRow 6フィールド構造とソート機能
- [必須] 動的クラスタ割り当て（オンデマンド）
- [必須] Linux先読みとの性能比較機能
- [必須] 詳細統計とメトリクス計算

### 8.2. 性能要件
- [目標] 計算複雑度O(1)のMC更新
- [目標] 実メモリ使用量 < 理論最大値の10%
- [目標] 論文結果との誤差 < 5%

### 8.3. 検証要件
- [必須] KVM/カーネルビルド相当ワークロードでの検証
- [必須] パラメータ感度分析（4×5マトリクス）
- [必須] ベースライン比較（Linux先読み vs CluMP）
- [推奨] 長期ワークロードでの安定性検証

## 9. 実装優先順位

### Phase 1: 核心アルゴリズム
1. MCRow構造とソート機能
2. 8ステップCluMPアルゴリズム
3. 動的クラスタ管理

### Phase 2: 比較・評価
4. Linux先読みベースライン
5. 詳細メトリクス計算
6. パラメータ分析機能

### Phase 3: 検証・最適化
7. 実ワークロード模擬
8. 性能チューニング
9. 文書化・テスト

## 10. 参考文献
- CluMP論文 Section 3.2: 構造設計
- CluMP論文 Section 3.3: 動作アルゴリズム  
- CluMP論文 Section 4: 性能評価方法
- Linux Kernel 5.4.0 先読み実装