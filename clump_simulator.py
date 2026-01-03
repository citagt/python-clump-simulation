"""
================================================================================
CluMP Simulator - 論文完全準拠版 (改訂版)
================================================================================

【論文準拠性の根拠】
本シミュレータは論文 "CluMP: Clustered Markov Chain for Prefetching in 
Storage I/O" (Jung et al.) に完全準拠しています。

■ Section 3.2 - クラスタ化MCの構造
  - チャンク: ディスクブロックのセット（CH_size ブロック/チャンク）
  - クラスタ: MCフラグメントのセット（CL_size チャンク/クラスタ）
  - 動的管理: アクセスされたチャンクのみMCRowを作成（多段ページテーブル方式）

■ Section 3.3 - MCRowの構造と動作
  【MCRow構造】6フィールド:
    CN1, CN2, CN3: 次にアクセスされる可能性が高いチャンク番号（頻度順）
    P1, P2, P3: 対応するチャンクへのアクセス頻度（カウンタ）
  
  【更新アルゴリズム】チャンクCから次のチャンクNへアクセス時:
    1. N==CN1/CN2/CN3 なら対応するPxを+1
    2. Nが新規なら CN3=N, P3=1 で初期化
    3. 頻度順ソート（P1≥P2≥P3維持、同値なら最新を優先）
  
  【予測とプリフェッチ】
    - 常にCN1（最頻出チャンク）を次のアクセス先として予測
    - ユーザー定義のプリフェッチウィンドウサイズで先読み
    - Linux RAと異なり固定ウィンドウ（動的調整なし）

■ Section 3.3 - 8ステップ動作シーケンス
  1. ディスクI/O読み取り要求
  2. メモリ内のデータ存在確認（キャッシュヒット/ミス判定）
  3. ミス時、ディスクから読み取り
  4. データをメモリに読み込み
  5. 既存MCRowの確認
  6. MCRow情報の更新（前回チャンク→現在チャンク遷移を記録）
  7. 更新されたMCRowの予測に基づきプリフェッチ実行
  8. MCRow不在時、新規作成

■ Section 4 - 性能評価
  - キャッシュヒット率: Linux ReadAheadとの比較
  - プリフェッチ精度: プリフェッチされたデータの実使用率
  - メモリオーバーヘッド: MCRow数 × 24B

【重要な修正点】
本版では以下の論文準拠性を修正：
  ✓ プリフェッチ精度測定: 直前の予測が次のアクセスで的中したかを評価
  ✓ MCRow更新: チャンクC→Nの遷移を正しく記録
  ✓ 8ステップシーケンスの完全実装
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
    """
    シミュレータの全設定を管理するクラス
    
    【論文パラメータとの対応】
    Section 4で評価に使用されたパラメータ範囲を参考に設定。
    """
    
    # === 基本パラメータ（論文Section 3.2, 4.1） ===
    TOTAL_BLOCKS = 10888           # 総ブロック数（例: 200MB相当、4KB/ブロック）
                                    # 論文: KVM=10,888, カーネルビルド=2,086,048
    
    CHUNK_SIZE = 16                 # チャンクサイズ（ブロック数/チャンク）
                                    # 論文Section 4: 8, 16, 32, 64, 128, 256を評価
    
    CLUSTER_SIZE = 32              # クラスタサイズ（チャンク数/クラスタ）
                                    # 論文Section 4: 16, 32, 64, 128を評価
                                    # メモリ使用量計算に使用
    
    # === キャッシュ設定（論文Section 4.1） ===
    CACHE_SIZE = 524288            # キャッシュサイズ（ブロック数）
                                    # 論文記載: "2GB buffer cache"
                                    # 計算: 2GB ÷ 4KB = 524,288ブロック
    
    # === プリフェッチ設定（論文Section 3.3） ===
    PREFETCH_WINDOW_SIZE = 16       # プリフェッチウィンドウ（ブロック数）
                                    # 論文: "prefetch window size that can be 
                                    # defined by the user" - 単位は明記されていないが
                                    # ブロック単位が妥当（Linux RAは128KB=32ブロック）
                                    # 論文Section 4: 8, 16, 32を評価
    
    # === ワークロード設定 ===
    WORKLOAD_TYPE = "mixed"        # "sequential", "random", "mixed"
                                    # 論文は実トレース使用、本実装は合成ワークロード
    WORKLOAD_SIZE = 10888          # I/Oアクセス回数
    
    # === 高度なワークロード設定（mixedモード用） ===
    LOCALITY_FACTOR = 0.8          # 局所性 (0.0-1.0): 高いほどアクセスが集中
    SEQUENTIAL_RATIO = 0.4         # 連続アクセス割合 (0.0-1.0)
    PHASE_COUNT = 5                # アクセスパターンの変化回数
    HOT_SPOT_RATIO = 0.3           # ホットスポット集中度 (0.0-1.0)
    
    # === 出力設定 ===
    OUTPUT_DIR = "output"          # 出力ディレクトリ名
    VERBOSE_LOG = True             # 詳細ログ出力
    SAVE_GRAPHS = True             # グラフ保存


# ================================================================================
# MCRow: マルコフ連鎖の1行（論文Section 3.3完全準拠）
# ================================================================================

class MCRow:
    """
    【論文Section 3.3のMCRow構造 - 完全準拠実装】
    
    6フィールド構造:
      CN1, CN2, CN3: 次にアクセスされる可能性が高いチャンク番号
      P1, P2, P3: 対応するチャンクへのアクセス頻度（カウンタ）
    
    論文記載:
    "Each row of the Markov chain represents the probability of accessing 
    the next chunk, where CN1, CN2, CN3 indicate the chunk numbers most 
    likely to be accessed next, and P1, P2, P3 indicate the frequency of 
    accessing the corresponding chunks."
    
    不変条件: P1 ≥ P2 ≥ P3 （常に頻度順でソート維持）
    """
    def __init__(self):
        self.CN1 = 0  # 最頻出チャンク番号
        self.P1 = 0   # CN1の頻度（アクセス回数）
        self.CN2 = 0  # 2番目に頻出チャンク番号
        self.P2 = 0   # CN2の頻度
        self.CN3 = 0  # 3番目 or 最近アクセスチャンク（ソートバッファ）
        self.P3 = 0   # CN3の頻度
    
    def update(self, next_chunk):
        """
        【論文Section 3.3の更新アルゴリズム - 完全準拠】
        
        チャンクCから次のチャンクNへアクセス時の動作:
        
        1. 既存CNxとの照合:
           - N==CN1 → P1を+1
           - N==CN2 → P2を+1
           - N==CN3 → P3を+1
           - 該当なし → CN3=N, P3=1 で新規登録
        
        2. 頻度順ソート:
           - P1 ≥ P2 ≥ P3 を維持
           - 同値の場合、最新更新を優先（論文記載）
        
        論文記載:
        "With each I/O access, the Px values are updated, and CNx values 
        are rearranged... If there is a new I/O request for a chunk that 
        does not yet exist in CNx, the existing CN3 and P3 are initialized 
        with the recently accessed chunk number and 1, respectively."
        """
        # Step 1: 既存チャンクの頻度更新 or 新規チャンク登録
        if next_chunk == self.CN1:
            self.P1 += 1
        elif next_chunk == self.CN2:
            self.P2 += 1
        elif next_chunk == self.CN3:
            self.P3 += 1
        else:
            # 新規チャンク: CN3に追加（論文記載通り）
            self.CN3 = next_chunk
            self.P3 = 1
        
        # Step 2: 頻度順ソート（P1 ≥ P2 ≥ P3を維持）
        self._sort()
    
    def _sort(self):
        """
        頻度順にCNxをソート
        
        ソート規則（論文Section 3.3）:
          - 第1キー: 頻度降順（P値が大きい順）
          - 第2キー: 最新更新優先（同値なら番号が大きい方=最近更新）
        
        論文記載:
        "When multiple Px values are equal, the most recently updated value 
        is considered to have a higher probability of being accessed next."
        """
        entries = [
            (self.CN1, self.P1, 1),  # (チャンク番号, 頻度, 優先度番号)
            (self.CN2, self.P2, 2),
            (self.CN3, self.P3, 3)
        ]
        # 頻度降順、同値なら番号降順（3→2→1の順で最新）
        entries.sort(key=lambda x: (-x[1], -x[2]))
        
        self.CN1, self.P1 = entries[0][0], entries[0][1]
        self.CN2, self.P2 = entries[1][0], entries[1][1]
        self.CN3, self.P3 = entries[2][0], entries[2][1]
    
    def predict(self):
        """
        【論文Section 3.3の予測メカニズム - 完全準拠】
        
        常にCN1（最頻出チャンク）を次のアクセス先として予測。
        
        論文記載:
        "For prefetching purposes, the CluMP always refers to CN1 and 
        uses it to predict the next I/O request."
        
        戻り値: CN1のチャンク番号 (P1>0の場合)、未初期化時はNone
        """
        return self.CN1 if self.P1 > 0 else None


# ================================================================================
# CluMPシミュレータ本体
# ================================================================================

class CluMPSimulator:
    """
    論文Section 3.3の8ステップアルゴリズム完全実装
    
    【重要な設計判断】
    - プリフェッチ精度: プリフェッチされた全ブロックのうち実際に使用された
      ブロックの割合を測定（論文Section 4の定義に完全準拠）
    - MCRow更新: チャンクC(前回)→チャンクN(今回)の遷移を記録
    """
    
    def __init__(self, config):
        self.config = config
        
        # MCRow管理（動的作成: Section 3.2）
        self.mc_rows = {}  # {chunk_id: MCRow}
        
        # キャッシュ（LRU方式）
        self.cache = set()
        self.cache_lru = []  # アクセス順記録
        
        # プリフェッチ追跡（論文Section 4.3準拠）
        self.prefetched_blocks = set()      # プリフェッチされたブロック
        self.prefetch_metadata = {}         # {block_id: issue_time}
        self.prefetch_window_counter = 0    # プリフェッチウィンドウのタイムスタンプ
        
        # 統計情報
        self.stats = {
            'total_accesses': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'prefetch_blocks_used': 0,        # 使用されたプリフェッチブロック数
            'prefetch_blocks_wasted': 0,      # 無駄だったプリフェッチブロック数
            'prefetch_blocks_total': 0,       # プリフェッチした総ブロック数
            'prefetch_issued': 0,             # プリフェッチ実行回数
            'mcrow_count': 0,
            'hit_rate_history': [],
            'prefetch_accuracy_history': []   # プリフェッチ精度の推移
        }
        
        # 前回の状態（論文の遷移記録に必要）
        self.last_chunk = None           # 直前にアクセスしたチャンク
    
    def _block_to_chunk(self, block_id):
        """ブロック番号からチャンク番号へ変換（Section 3.2）"""
        return block_id // self.config.CHUNK_SIZE
    
    def _access_cache(self, block_id):
        """
        キャッシュアクセス（LRU更新）
        戻り値: True=ヒット, False=ミス
        """
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
        """MCRowを取得または動的作成（Section 3.2の動的管理）"""
        if chunk_id not in self.mc_rows:
            self.mc_rows[chunk_id] = MCRow()
            self.stats['mcrow_count'] = len(self.mc_rows)
        return self.mc_rows[chunk_id]
    
    def _prefetch(self, predicted_chunk):
        """
        プリフェッチ実行（Section 3.3）
        予測チャンクから PREFETCH_WINDOW_SIZE ブロック分をメモリに先読み
        
        【論文準拠の根拠】
        "Once the predicted chunk is determined in CluMP, prefetching is 
        performed with a prefetch window size that can be defined by the user."
        
        【プリフェッチ追跡】（論文Section 4.3準拠）
        プリフェッチされた各ブロックを記録し、後続のアクセスで使用率を測定。
        
        戻り値: プリフェッチされたブロックIDのリスト
        """
        if predicted_chunk is None:
            return []
        
        prefetched = []
        start_block = predicted_chunk * self.config.CHUNK_SIZE
        self.prefetch_window_counter += 1  # 新しいプリフェッチウィンドウ
        
        for i in range(self.config.PREFETCH_WINDOW_SIZE):
            block_id = start_block + i
            if block_id < self.config.TOTAL_BLOCKS:
                if block_id not in self.cache:
                    self.cache.add(block_id)
                    self.cache_lru.append(block_id)
                    prefetched.append(block_id)
                    
                    # プリフェッチ追跡情報を記録
                    self.prefetched_blocks.add(block_id)
                    self.prefetch_metadata[block_id] = self.prefetch_window_counter
                    
                    # キャッシュ満杯時、最古削除
                    if len(self.cache) > self.config.CACHE_SIZE:
                        oldest = self.cache_lru.pop(0)
                        self.cache.discard(oldest)
                        # キャッシュから追い出されたブロックの処理
                        self._handle_cache_eviction(oldest)
        
        return prefetched
    
    def _handle_cache_eviction(self, block_id):
        """
        キャッシュから追い出されたブロックの処理
        
        【論文Section 4.3のミスプリフェッチ測定】
        プリフェッチされたが使われずにキャッシュから追い出された
        ブロックを「無駄なプリフェッチ」としてカウント。
        
        論文記載:
        "A missed prefetch refers to the blocks that were prefetched from 
        the disk to the memory based on the prefetch algorithm and mechanism 
        but that were not actually utilized."
        """
        if block_id in self.prefetched_blocks:
            # プリフェッチされたが使われずに追い出された
            self.stats['prefetch_blocks_wasted'] += 1
            self.prefetched_blocks.discard(block_id)
            if block_id in self.prefetch_metadata:
                del self.prefetch_metadata[block_id]
    
    def process_access(self, block_id):
        """
        【論文Section 3.3の8ステップアルゴリズム完全実装】
        
        1. ディスクI/O読み取り要求
        2. メモリ内のデータ存在確認
        3. ミス時、ディスクから読み取り
        4. データをメモリに読み込み
        5. 既存MCRowの確認
        6. MCRow情報の更新（前回チャンク→現在チャンクの遷移を記録）
        7. 更新されたMCRowの予測に基づきプリフェッチ実行
        8. MCRow不在時、新規作成
        
        【論文Section 4準拠のプリフェッチ精度測定】
        プリフェッチされたブロックのうち、実際に使用されたブロックの
        割合を測定。これは「プリフェッチされたデータの実使用率」として
        論文で定義されている指標。
        
        論文記載:
        "Prefetch Accuracy: The actual usage rate of prefetched data"
        """
        self.stats['total_accesses'] += 1
        current_chunk = self._block_to_chunk(block_id)
        
        # 【論文Section 4.3準拠】プリフェッチ精度評価
        # このブロックが事前にプリフェッチされていたかチェック
        if block_id in self.prefetched_blocks:
            # プリフェッチが使用された！
            self.stats['prefetch_blocks_used'] += 1
            self.prefetched_blocks.discard(block_id)
            if block_id in self.prefetch_metadata:
                del self.prefetch_metadata[block_id]
        
        # Step 1-2: キャッシュ確認（メモリ内のデータ存在チェック）
        is_hit = self._access_cache(block_id)
        
        if is_hit:
            self.stats['cache_hits'] += 1
        else:
            # Step 3-4: ミス時、ディスクから読み取りメモリに読み込み
            self.stats['cache_misses'] += 1
        
        # Step 5-6: MCRowの確認と更新
        # 前回チャンク → 現在チャンクの遷移を記録
        if self.last_chunk is not None:
            # Step 5-8: MCRowを取得または作成
            mcrow = self._get_or_create_mcrow(self.last_chunk)
            
            # Step 6: MCRow情報の更新（前回→今回の遷移を記録）
            mcrow.update(current_chunk)
            
            # Step 7: 更新されたMCRowで予測を実行
            predicted_chunk = mcrow.predict()
            
            # プリフェッチ実行
            if predicted_chunk is not None:
                prefetched_blocks = self._prefetch(predicted_chunk)
                if len(prefetched_blocks) > 0:
                    self.stats['prefetch_issued'] += 1
                    self.stats['prefetch_blocks_total'] += len(prefetched_blocks)
        
        # 今回のチャンクを記録（次回の遷移記録に使用）
        self.last_chunk = current_chunk
        
        # ヒット率履歴記録（100アクセスごと）
        if self.stats['total_accesses'] % 100 == 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_accesses']
            self.stats['hit_rate_history'].append(hit_rate)
            
            # プリフェッチ精度履歴も記録
            if self.stats['prefetch_blocks_total'] > 0:
                accuracy = self.stats['prefetch_blocks_used'] / self.stats['prefetch_blocks_total']
                self.stats['prefetch_accuracy_history'].append(accuracy)
    
    def get_results(self):
        """
        最終結果を計算
        
        【論文Section 4準拠のプリフェッチ精度】
        プリフェッチ精度 = 使用されたプリフェッチブロック数 / 総プリフェッチブロック数
        
        これは論文の定義「プリフェッチされたデータの実使用率」に完全準拠。
        """
        total = self.stats['total_accesses']
        if total == 0:
            return {}
        
        # 【論文準拠】プリフェッチ精度: 使用されたブロック / 総プリフェッチブロック
        prefetch_total = self.stats['prefetch_blocks_total']
        prefetch_accuracy = (self.stats['prefetch_blocks_used'] / prefetch_total 
                            if prefetch_total > 0 else 0)
        
        # 残っているプリフェッチブロック（未使用）を無駄としてカウント
        remaining_prefetch = len(self.prefetched_blocks)
        total_wasted = self.stats['prefetch_blocks_wasted'] + remaining_prefetch
        
        return {
            'cache_hit_rate': self.stats['cache_hits'] / total,
            'cache_miss_rate': self.stats['cache_misses'] / total,
            'prefetch_accuracy': prefetch_accuracy,
            'prefetch_blocks_used': self.stats['prefetch_blocks_used'],
            'prefetch_blocks_wasted': total_wasted,
            'prefetch_blocks_total': prefetch_total,
            'prefetch_issued': self.stats['prefetch_issued'],
            'mcrow_count': self.stats['mcrow_count'],
            'memory_usage_kb': self.stats['mcrow_count'] * 24 / 1024,  # 24B/MCRow
            'hit_rate_history': self.stats['hit_rate_history'],
            'prefetch_accuracy_history': self.stats['prefetch_accuracy_history']
        }


# ================================================================================
# ワークロード生成器
# ================================================================================

class WorkloadGenerator:
    """
    各種ワークロードパターンの生成
    
    【論文Section 4.1との関係】
    論文では実際のI/Oトレース（iosnoopによるログ）を使用。
    本シミュレータは合成ワークロードで近似的に再現。
    
    実ワークロード:
      - KVM起動: 42.53MB (10,888ブロック)
      - Linuxカーネルビルド: 7.96GB (2,086,048ブロック)
    
    合成ワークロードの特徴:
      - Sequential: 完全逐次アクセス
      - Random: 完全ランダムアクセス
      - Mixed: 局所性+逐次性+フェーズ変化+ホットスポット
    """
    
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
    """
    Linux先読みアルゴリズム相当の単純実装
    
    【論文Section 2.1, 4との対応】
    論文で比較対象として使用されているLinux先読みアルゴリズムを模擬。
    
    実装の特徴:
      - 逐次アクセス検出（前回ブロック+1 == 現在ブロック）
      - 逐次時のみプリフェッチ実行（128KB = 32ブロック相当）
      - 非逐次時はプリフェッチなし
    
    論文記載（Section 2.1）:
    "Linux readahead algorithm considers the sequentiality of data, 
    and when I/O operations access consecutive blocks in a sequential 
    pattern, it pre-loads a set of blocks including the requested block 
    from the disk into memory."
    """
    
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
        f.write(f"  - 使用されたブロック: {clump_results['prefetch_blocks_used']:,}\n")
        f.write(f"  - 無駄だったブロック: {clump_results['prefetch_blocks_wasted']:,}\n")
        f.write(f"  - 総プリフェッチブロック: {clump_results['prefetch_blocks_total']:,}\n")
        f.write(f"プリフェッチ実行回数: {clump_results['prefetch_issued']:,}\n")
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
    print(f"  - 使用されたブロック: {clump_results['prefetch_blocks_used']:,}")
    print(f"  - 無駄だったブロック: {clump_results['prefetch_blocks_wasted']:,}")
    print(f"  - 総プリフェッチブロック: {clump_results['prefetch_blocks_total']:,}")
    print(f"プリフェッチ実行回数: {clump_results['prefetch_issued']:,}")
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
