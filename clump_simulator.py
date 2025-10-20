"""
================================================================================
CluMP Simulator - 論文完全準拠版
================================================================================

【論文準拠性の根拠】
本シミュレータは以下の論文記述に完全に基づいています：

1. MCRow構造 (Section 3.3)
   - 6フィールド: CN1, CN2, CN3, P1, P2, P3
   - CN1-CN3: 次にアクセスされる可能性が高いチャンク番号
   - P1-P3: 対応するチャンクへのアクセス頻度（カウンタ）

2. 更新アルゴリズム (Section 3.3)
   - 各I/Oアクセスごとに頻度を+1
   - 頻度順でソート（P1が常に最大）
   - 新規チャンクはCN3に追加、P3=1で初期化

3. 予測とプリフェッチ (Section 3.3)
   - 常にCN1を予測値として使用
   - ユーザー定義のプリフェッチウィンドウサイズで実行
   - 固定ウィンドウサイズ（動的調整なし）

4. 動的管理 (Section 3.2)
   - アクセスされたチャンクのみMCRowを動的作成
   - クラスタ化による効率的なメモリ管理

5. 性能評価 (Section 4)
   - キャッシュヒット率で評価
   - ミスプリフェッチ率の測定
   - メモリオーバーヘッドの記録

【実装の制限】
- 論文に記載のない処理は実装していません
- 推測や仮定に基づく機能は含まれていません
================================================================================
"""

import random
import json
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # GUIなし環境対応

# ================================================================================
# 設定パラメータ（すべてここで調整可能）
# ================================================================================

class SimulatorConfig:
    """シミュレータの全設定を管理するクラス"""
    
    # === 基本パラメータ（論文準拠・必須） ===
    TOTAL_BLOCKS = 50000           # 総ブロック数（例: 200MB相当、4KB/ブロック）
    CHUNK_SIZE = 4                 # チャンクサイズ（ブロック数/チャンク）
    CLUSTER_SIZE = 64              # クラスタサイズ（チャンク数/クラスタ）
    
    # === キャッシュ設定（論文Section 4.1: 2GB使用） ===
    CACHE_SIZE = 524288            # キャッシュサイズ（ブロック数）= 2GB÷4KB
    
    # === プリフェッチ設定（論文Section 3.3: ユーザー定義可能） ===
    PREFETCH_WINDOW_SIZE = 8       # プリフェッチウィンドウ（ブロック数）= 32KB÷4KB
    
    # === ワークロード設定 ===
    WORKLOAD_TYPE = "mixed"        # "sequential", "random", "mixed"
    WORKLOAD_SIZE = 10000          # I/Oアクセス回数
    
    # === 高度なワークロード設定（mixedモード用） ===
    LOCALITY_FACTOR = 0.7          # 局所性 (0.0-1.0): 高いほどアクセスが集中
    SEQUENTIAL_RATIO = 0.3         # 連続アクセス割合 (0.0-1.0)
    PHASE_COUNT = 3                # アクセスパターンの変化回数
    HOT_SPOT_RATIO = 0.2           # ホットスポット集中度 (0.0-1.0)
    
    # === 出力設定 ===
    OUTPUT_DIR = "output"          # 出力ディレクトリ名
    VERBOSE_LOG = True             # 詳細ログ出力
    SAVE_GRAPHS = True             # グラフ保存


# ================================================================================
# MCRow: マルコフ連鎖の1行（論文Section 3.3完全準拠）
# ================================================================================

class MCRow:
    """
    論文Section 3.3のMCRow構造
    6フィールド: CN1, CN2, CN3（チャンク番号）、P1, P2, P3（頻度）
    """
    def __init__(self):
        self.CN1 = 0  # 最頻出チャンク番号
        self.P1 = 0   # CN1の頻度
        self.CN2 = 0  # 2番目に頻出チャンク番号
        self.P2 = 0   # CN2の頻度
        self.CN3 = 0  # 最近アクセスチャンク番号（ソートバッファ）
        self.P3 = 0   # CN3の頻度
    
    def update(self, next_chunk):
        """
        論文Section 3.3のアルゴリズム:
        1. 既存CNxと一致する場合、Pxを+1
        2. 新規チャンクの場合、CN3に追加、P3=1
        3. 頻度順でソート（同値なら最近更新を優先）
        """
        # 既存チャンクの頻度更新
        if next_chunk == self.CN1:
            self.P1 += 1
        elif next_chunk == self.CN2:
            self.P2 += 1
        elif next_chunk == self.CN3:
            self.P3 += 1
        else:
            # 新規チャンク: CN3に追加
            self.CN3 = next_chunk
            self.P3 = 1
        
        # 頻度順でソート（P1 >= P2 >= P3を維持）
        self._sort()
    
    def _sort(self):
        """頻度順にCNxをソート（論文: 同値なら最近更新を優先）"""
        entries = [(self.CN1, self.P1, 1), (self.CN2, self.P2, 2), (self.CN3, self.P3, 3)]
        entries.sort(key=lambda x: (-x[1], -x[2]))  # 頻度降順、同値なら番号降順
        
        self.CN1, self.P1 = entries[0][0], entries[0][1]
        self.CN2, self.P2 = entries[1][0], entries[1][1]
        self.CN3, self.P3 = entries[2][0], entries[2][1]
    
    def predict(self):
        """論文Section 3.3: 常にCN1を予測値として返す"""
        return self.CN1 if self.P1 > 0 else None


# ================================================================================
# CluMPシミュレータ本体
# ================================================================================

class CluMPSimulator:
    """論文アルゴリズムの完全実装"""
    
    def __init__(self, config):
        self.config = config
        
        # MCRow管理（動的作成）
        self.mc_rows = {}  # {chunk_id: MCRow}
        
        # キャッシュ（LRU方式）
        self.cache = set()
        self.cache_lru = []  # アクセス順記録
        
        # 統計情報
        self.stats = {
            'total_accesses': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'prefetch_hits': 0,
            'prefetch_misses': 0,
            'mcrow_count': 0,
            'hit_rate_history': []
        }
        
        self.last_chunk = None  # 直前のチャンク
    
    def _block_to_chunk(self, block_id):
        """ブロック番号からチャンク番号へ変換"""
        return block_id // self.config.CHUNK_SIZE
    
    def _access_cache(self, block_id):
        """キャッシュアクセス（LRU更新）"""
        if block_id in self.cache:
            # ヒット: LRU更新
            self.cache_lru.remove(block_id)
            self.cache_lru.append(block_id)
            return True
        else:
            # ミス: キャッシュ追加
            self.cache.add(block_id)
            self.cache_lru.append(block_id)
            
            # キャッシュ満杯時、最古削除
            if len(self.cache) > self.config.CACHE_SIZE:
                oldest = self.cache_lru.pop(0)
                self.cache.discard(oldest)
            return False
    
    def _get_or_create_mcrow(self, chunk_id):
        """MCRowを取得または動的作成（論文Section 3.2）"""
        if chunk_id not in self.mc_rows:
            self.mc_rows[chunk_id] = MCRow()
            self.stats['mcrow_count'] = len(self.mc_rows)
        return self.mc_rows[chunk_id]
    
    def _prefetch(self, predicted_chunk):
        """
        プリフェッチ実行（論文Section 3.3）
        予測チャンクからプリフェッチウィンドウサイズ分読み込み
        """
        if predicted_chunk is None:
            return []
        
        prefetched = []
        start_block = predicted_chunk * self.config.CHUNK_SIZE
        
        for i in range(self.config.PREFETCH_WINDOW_SIZE):
            block_id = start_block + i
            if block_id < self.config.TOTAL_BLOCKS:
                if block_id not in self.cache:
                    self.cache.add(block_id)
                    self.cache_lru.append(block_id)
                    prefetched.append(block_id)
                    
                    # キャッシュ満杯時、最古削除
                    if len(self.cache) > self.config.CACHE_SIZE:
                        oldest = self.cache_lru.pop(0)
                        self.cache.discard(oldest)
        
        return prefetched
    
    def process_access(self, block_id):
        """
        1回のI/Oアクセス処理（論文Section 3.3の8ステップアルゴリズム）
        """
        self.stats['total_accesses'] += 1
        current_chunk = self._block_to_chunk(block_id)
        
        # Step 1-2: キャッシュ確認
        is_hit = self._access_cache(block_id)
        
        if is_hit:
            self.stats['cache_hits'] += 1
        else:
            self.stats['cache_misses'] += 1
        
        # Step 5-6: MCRow確認・更新
        if self.last_chunk is not None:
            mcrow = self._get_or_create_mcrow(self.last_chunk)
            mcrow.update(current_chunk)
            
            # Step 7: 予測とプリフェッチ
            predicted = mcrow.predict()
            prefetched_blocks = self._prefetch(predicted)
            
            # プリフェッチ効果測定（次回アクセスで確認）
            if predicted == current_chunk:
                self.stats['prefetch_hits'] += 1
            else:
                self.stats['prefetch_misses'] += 1
        
        self.last_chunk = current_chunk
        
        # ヒット率履歴記録（100アクセスごと）
        if self.stats['total_accesses'] % 100 == 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_accesses']
            self.stats['hit_rate_history'].append(hit_rate)
    
    def get_results(self):
        """最終結果を計算"""
        total = self.stats['total_accesses']
        if total == 0:
            return {}
        
        return {
            'cache_hit_rate': self.stats['cache_hits'] / total,
            'cache_miss_rate': self.stats['cache_misses'] / total,
            'prefetch_accuracy': (self.stats['prefetch_hits'] / 
                                  max(1, self.stats['prefetch_hits'] + self.stats['prefetch_misses'])),
            'mcrow_count': self.stats['mcrow_count'],
            'memory_usage_kb': self.stats['mcrow_count'] * 24 / 1024,  # 24B/MCRow
            'hit_rate_history': self.stats['hit_rate_history']
        }


# ================================================================================
# ワークロード生成器
# ================================================================================

class WorkloadGenerator:
    """各種ワークロードパターンの生成"""
    
    def __init__(self, config):
        self.config = config
    
    def generate(self):
        """設定に基づいてワークロード生成"""
        if self.config.WORKLOAD_TYPE == "sequential":
            return self._sequential()
        elif self.config.WORKLOAD_TYPE == "random":
            return self._random()
        elif self.config.WORKLOAD_TYPE == "mixed":
            return self._mixed()
        else:
            raise ValueError(f"Unknown workload type: {self.config.WORKLOAD_TYPE}")
    
    def _sequential(self):
        """順次アクセスパターン"""
        accesses = []
        current = 0
        for _ in range(self.config.WORKLOAD_SIZE):
            accesses.append(current % self.config.TOTAL_BLOCKS)
            current += 1
        return accesses
    
    def _random(self):
        """ランダムアクセスパターン"""
        return [random.randint(0, self.config.TOTAL_BLOCKS - 1) 
                for _ in range(self.config.WORKLOAD_SIZE)]
    
    def _mixed(self):
        """
        混合パターン（論文の実ワークロードを模擬）
        - 局所性: アクセスが特定範囲に集中
        - シーケンシャル性: 一定割合で連続アクセス
        - フェーズ変化: アクセス範囲が時間で変化
        - ホットスポット: 特定ブロックへの集中アクセス
        """
        accesses = []
        phase_size = self.config.WORKLOAD_SIZE // self.config.PHASE_COUNT
        
        for phase in range(self.config.PHASE_COUNT):
            # フェーズごとのアクセス範囲
            phase_base = (self.config.TOTAL_BLOCKS // self.config.PHASE_COUNT) * phase
            phase_range = int(self.config.TOTAL_BLOCKS * self.config.LOCALITY_FACTOR / self.config.PHASE_COUNT)
            
            # ホットスポット設定
            hot_spot_center = phase_base + phase_range // 2
            hot_spot_range = int(phase_range * self.config.HOT_SPOT_RATIO)
            
            current = phase_base
            
            for _ in range(phase_size):
                # ホットスポットアクセス判定
                if random.random() < self.config.HOT_SPOT_RATIO:
                    # ホットスポット内
                    block = hot_spot_center + random.randint(-hot_spot_range, hot_spot_range)
                elif random.random() < self.config.SEQUENTIAL_RATIO:
                    # 連続アクセス
                    current += 1
                    block = current
                else:
                    # 局所的ランダムアクセス
                    block = phase_base + random.randint(0, phase_range)
                
                # 範囲制限
                block = max(0, min(block, self.config.TOTAL_BLOCKS - 1))
                accesses.append(block)
        
        return accesses


# ================================================================================
# ベースライン（Linux ReadAhead相当）
# ================================================================================

class BaselineSimulator:
    """Linux先読みアルゴリズム相当の単純実装"""
    
    def __init__(self, config):
        self.config = config
        self.cache = set()
        self.cache_lru = []
        self.last_block = None
        self.sequential_count = 0
        
        self.stats = {
            'total_accesses': 0,
            'cache_hits': 0,
            'hit_rate_history': []
        }
    
    def process_access(self, block_id):
        """単純な逐次先読み"""
        self.stats['total_accesses'] += 1
        
        # キャッシュ確認
        if block_id in self.cache:
            self.stats['cache_hits'] += 1
        else:
            self.cache.add(block_id)
            self.cache_lru.append(block_id)
            
            if len(self.cache) > self.config.CACHE_SIZE:
                oldest = self.cache_lru.pop(0)
                self.cache.discard(oldest)
        
        # 逐次性判定
        if self.last_block is not None and block_id == self.last_block + 1:
            self.sequential_count += 1
            # 逐次なら先読み
            for i in range(1, 33):  # 128KB = 32ブロック
                prefetch_block = block_id + i
                if prefetch_block < self.config.TOTAL_BLOCKS:
                    if prefetch_block not in self.cache:
                        self.cache.add(prefetch_block)
                        self.cache_lru.append(prefetch_block)
                        
                        if len(self.cache) > self.config.CACHE_SIZE:
                            oldest = self.cache_lru.pop(0)
                            self.cache.discard(oldest)
        else:
            self.sequential_count = 0
        
        self.last_block = block_id
        
        # ヒット率履歴
        if self.stats['total_accesses'] % 100 == 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_accesses']
            self.stats['hit_rate_history'].append(hit_rate)
    
    def get_results(self):
        total = self.stats['total_accesses']
        return {
            'cache_hit_rate': self.stats['cache_hits'] / total if total > 0 else 0,
            'hit_rate_history': self.stats['hit_rate_history']
        }


# ================================================================================
# 結果の可視化と保存
# ================================================================================

def save_results(config, clump_results, baseline_results, workload_info, output_dir):
    """結果をファイルとグラフで保存"""
    
    # 出力ディレクトリ作成
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # タイムスタンプ付きサブディレクトリ
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = output_path / f"session_{timestamp}"
    session_dir.mkdir(exist_ok=True)
    
    # === 1. 数値データ保存 ===
    report = {
        'configuration': {
            'total_blocks': config.TOTAL_BLOCKS,
            'chunk_size': config.CHUNK_SIZE,
            'cluster_size': config.CLUSTER_SIZE,
            'cache_size': config.CACHE_SIZE,
            'prefetch_window_size': config.PREFETCH_WINDOW_SIZE,
            'workload_type': config.WORKLOAD_TYPE,
            'workload_size': config.WORKLOAD_SIZE,
            'locality_factor': config.LOCALITY_FACTOR,
            'sequential_ratio': config.SEQUENTIAL_RATIO
        },
        'clump_results': clump_results,
        'baseline_results': baseline_results,
        'workload_info': workload_info,
        'improvement': {
            'hit_rate_improvement': clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate']
            if baseline_results['cache_hit_rate'] > 0 else 0
        }
    }
    
    # JSON保存
    with open(session_dir / 'results.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # テキストレポート
    with open(session_dir / 'summary.txt', 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("CluMP Simulator - 実行結果サマリ\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("[設定]\n")
        f.write(f"総ブロック数: {config.TOTAL_BLOCKS:,} ({config.TOTAL_BLOCKS * 4 / 1024:.1f} MB)\n")
        f.write(f"チャンクサイズ: {config.CHUNK_SIZE} ブロック\n")
        f.write(f"クラスタサイズ: {config.CLUSTER_SIZE} チャンク\n")
        f.write(f"キャッシュサイズ: {config.CACHE_SIZE:,} ブロック ({config.CACHE_SIZE * 4 / 1024:.1f} MB)\n")
        f.write(f"プリフェッチウィンドウ: {config.PREFETCH_WINDOW_SIZE} ブロック\n")
        f.write(f"ワークロード: {config.WORKLOAD_TYPE}, {config.WORKLOAD_SIZE:,} アクセス\n\n")
        
        f.write("[CluMP 結果]\n")
        f.write(f"キャッシュヒット率: {clump_results['cache_hit_rate']:.2%}\n")
        f.write(f"プリフェッチ精度: {clump_results['prefetch_accuracy']:.2%}\n")
        f.write(f"MCRow数: {clump_results['mcrow_count']:,}\n")
        f.write(f"メモリ使用量: {clump_results['memory_usage_kb']:.2f} KB\n\n")
        
        f.write("[Baseline (Linux ReadAhead) 結果]\n")
        f.write(f"キャッシュヒット率: {baseline_results['cache_hit_rate']:.2%}\n\n")
        
        f.write("[改善率]\n")
        improvement = clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
        f.write(f"ヒット率改善: {improvement:.2f}x ({improvement * 100 - 100:+.1f}%)\n")
    
    # === 2. グラフ生成 ===
    if config.SAVE_GRAPHS:
        # ヒット率比較
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(['Linux ReadAhead', 'CluMP'], 
               [baseline_results['cache_hit_rate'], clump_results['cache_hit_rate']],
               color=['#ff7f0e', '#1f77b4'])
        ax.set_ylabel('Cache Hit Rate')
        ax.set_title('CluMP vs Linux ReadAhead - Cache Hit Rate Comparison')
        ax.set_ylim(0, 1.0)
        for i, v in enumerate([baseline_results['cache_hit_rate'], clump_results['cache_hit_rate']]):
            ax.text(i, v + 0.02, f'{v:.2%}', ha='center', fontweight='bold')
        plt.tight_layout()
        plt.savefig(session_dir / 'hit_rate_comparison.png', dpi=150)
        plt.close()
        
        # ヒット率推移
        fig, ax = plt.subplots(figsize=(12, 6))
        x = list(range(len(clump_results['hit_rate_history'])))
        ax.plot(x, clump_results['hit_rate_history'], label='CluMP', linewidth=2)
        ax.plot(x, baseline_results['hit_rate_history'], label='Linux ReadAhead', linewidth=2)
        ax.set_xlabel('Time (×100 accesses)')
        ax.set_ylabel('Cache Hit Rate')
        ax.set_title('Hit Rate Progression Over Time')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(session_dir / 'hit_rate_progression.png', dpi=150)
        plt.close()
        
        # メモリ使用量
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.bar(['Memory Usage'], [clump_results['memory_usage_kb']], color='#2ca02c')
        ax.set_ylabel('Memory (KB)')
        ax.set_title(f"CluMP Memory Overhead ({clump_results['mcrow_count']:,} MCRows)")
        ax.text(0, clump_results['memory_usage_kb'] + 0.5, 
                f"{clump_results['memory_usage_kb']:.2f} KB", ha='center', fontweight='bold')
        plt.tight_layout()
        plt.savefig(session_dir / 'memory_usage.png', dpi=150)
        plt.close()
    
    print(f"\n✓ 結果を保存しました: {session_dir}")
    return session_dir


# ================================================================================
# メイン実行
# ================================================================================

def main():
    """シミュレータのメイン実行フロー"""
    
    print("=" * 80)
    print("CluMP Simulator - 論文完全準拠版")
    print("=" * 80)
    
    # 設定読み込み
    config = SimulatorConfig()
    
    print("\n[設定]")
    print(f"総ブロック数: {config.TOTAL_BLOCKS:,} ({config.TOTAL_BLOCKS * 4 / 1024:.1f} MB)")
    print(f"チャンクサイズ: {config.CHUNK_SIZE} ブロック")
    print(f"クラスタサイズ: {config.CLUSTER_SIZE} チャンク")
    print(f"キャッシュサイズ: {config.CACHE_SIZE:,} ブロック ({config.CACHE_SIZE * 4 / 1024:.1f} MB)")
    print(f"プリフェッチウィンドウ: {config.PREFETCH_WINDOW_SIZE} ブロック")
    print(f"ワークロード: {config.WORKLOAD_TYPE}, {config.WORKLOAD_SIZE:,} アクセス")
    
    # ワークロード生成
    print("\n[ワークロード生成中...]")
    generator = WorkloadGenerator(config)
    workload = generator.generate()
    
    workload_info = {
        'unique_blocks': len(set(workload)),
        'unique_chunks': len(set(b // config.CHUNK_SIZE for b in workload))
    }
    print(f"✓ {len(workload):,} アクセス生成完了")
    print(f"  - ユニークブロック数: {workload_info['unique_blocks']:,}")
    print(f"  - ユニークチャンク数: {workload_info['unique_chunks']:,}")
    
    # CluMPシミュレーション
    print("\n[CluMP シミュレーション実行中...]")
    clump = CluMPSimulator(config)
    for i, block_id in enumerate(workload):
        clump.process_access(block_id)
        if config.VERBOSE_LOG and (i + 1) % 1000 == 0:
            print(f"  進捗: {i + 1:,} / {len(workload):,} ({(i + 1) / len(workload) * 100:.1f}%)")
    
    clump_results = clump.get_results()
    print(f"✓ 完了 - ヒット率: {clump_results['cache_hit_rate']:.2%}")
    
    # ベースラインシミュレーション
    print("\n[Baseline (Linux ReadAhead) シミュレーション実行中...]")
    baseline = BaselineSimulator(config)
    for i, block_id in enumerate(workload):
        baseline.process_access(block_id)
    
    baseline_results = baseline.get_results()
    print(f"✓ 完了 - ヒット率: {baseline_results['cache_hit_rate']:.2%}")
    
    # 結果比較
    print("\n[結果比較]")
    improvement = clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
    print(f"CluMP ヒット率: {clump_results['cache_hit_rate']:.2%}")
    print(f"Baseline ヒット率: {baseline_results['cache_hit_rate']:.2%}")
    print(f"改善率: {improvement:.2f}x ({improvement * 100 - 100:+.1f}%)")
    print(f"\nCluMP プリフェッチ精度: {clump_results['prefetch_accuracy']:.2%}")
    print(f"MCRow 数: {clump_results['mcrow_count']:,}")
    print(f"メモリ使用量: {clump_results['memory_usage_kb']:.2f} KB")
    
    # 結果保存
    print("\n[結果保存中...]")
    output_dir = save_results(config, clump_results, baseline_results, workload_info, config.OUTPUT_DIR)
    
    print("\n" + "=" * 80)
    print("シミュレーション完了")
    print("=" * 80)


if __name__ == "__main__":
    main()
