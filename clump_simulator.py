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
from multiprocessing import Pool, cpu_count
import numpy as np
from scipy import stats as scipy_stats
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
    TOTAL_BLOCKS = 10888            # 総ブロック数（例: 200MB相当、4KB/ブロック）
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
    LOCALITY_FACTOR = 0.7          # 局所性 (0.0-1.0): 高いほどアクセスが集中
                                    # 0.7 = 70%の範囲に集中（実アプリの典型値）
    SEQUENTIAL_RATIO = 0.3         # 連続アクセス割合 (0.0-1.0)
                                    # 0.3 = 30%が連続（論文結果から逆算）
    PHASE_COUNT = 8                # アクセスパターンの変化回数
                                    # ビルドプロセスの段階を模擬（8段階）
    HOT_SPOT_RATIO = 0.2           # ホットスポット集中度 (0.0-1.0)
                                    # 0.2 = 20%がホットデータ（パレートの法則）
    
    # === 改良版CluMPパラメータ ===
    ALPHA_THRESHOLD = 0.5          # CN2を含める閾値（P2/P1 >= α）
    BETA_THRESHOLD = 0.3           # CN3を含める閾値（P3/P1 >= β）
    
    # === マルチ試行設定 ===
    NUM_TRIALS = 100                 # 試行回数（1=シングル実行、10+=統計分析用）
    RANDOM_SEED_BASE = 42          # ランダムシードの基準値（再現性確保）
    USE_PARALLEL = True           # CPU並列処理を使用（NUM_TRIALS > 1時のみ有効）
    MAX_WORKERS = None             # 並列ワーカー数（Noneで自動：CPU数）
    
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
    
    def predict_multi(self, alpha_threshold, beta_threshold):
        """
        【改良版】複数候補予測メカニズム
        
        信頼度比率に基づいてCN1, CN2, CN3から予測候補を選択。
        
        アルゴリズム:
          1. CN1は常に含める（P1 > 0の場合）
          2. P2/P1 >= α なら CN2を追加
          3. P3/P1 >= β なら CN3を追加
        
        引数:
          alpha_threshold: CN2を含める閾値
          beta_threshold: CN3を含める閾値
        
        戻り値: 予測チャンク番号のリスト
        """
        if self.P1 == 0:
            return []
        
        candidates = [self.CN1]  # CN1は必ず含める
        
        # CN2の信頼度判定
        if self.P2 > 0 and (self.P2 / self.P1) >= alpha_threshold:
            if self.CN2 not in candidates:  # 重複回避
                candidates.append(self.CN2)
        
        # CN3の信頼度判定
        if self.P3 > 0 and (self.P3 / self.P1) >= beta_threshold:
            if self.CN3 not in candidates:  # 重複回避
                candidates.append(self.CN3)
        
        return candidates


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
# 改良版CluMPシミュレータ（複数候補予測）
# ================================================================================

class ImprovedCluMPSimulator(CluMPSimulator):
    """
    改良版CluMP: 信頼度比率ベースの複数候補プリフェッチ
    
    【改良点】
    従来のCluMPはCN1のみを予測に使用するが、本版ではMCRowが保持する
    CN2, CN3も信頼度に応じて活用することで、予測のカバレッジを向上させる。
    
    【アルゴリズム】
    1. CN1は常にプリフェッチ対象（最頻出）
    2. P2/P1 >= α なら CN2もプリフェッチ
    3. P3/P1 >= β なら CN3もプリフェッチ
    
    これにより、アクセスパターンが複数の遷移先を持つ場合に
    より多くのケースをカバーできる。
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.alpha = config.ALPHA_THRESHOLD
        self.beta = config.BETA_THRESHOLD
    
    def process_access(self, block_id):
        """
        改良版の8ステップアルゴリズム
        
        従来版との違いは Step 7 のみ:
          従来: CN1のみ予測
          改良: CN1, CN2, CN3を信頼度で選択
        """
        self.stats['total_accesses'] += 1
        current_chunk = self._block_to_chunk(block_id)
        
        # プリフェッチ精度評価
        if block_id in self.prefetched_blocks:
            self.stats['prefetch_blocks_used'] += 1
            self.prefetched_blocks.discard(block_id)
            if block_id in self.prefetch_metadata:
                del self.prefetch_metadata[block_id]
        
        # Step 1-2: キャッシュ確認
        is_hit = self._access_cache(block_id)
        
        if is_hit:
            self.stats['cache_hits'] += 1
        else:
            self.stats['cache_misses'] += 1
        
        # Step 5-6: MCRowの確認と更新
        if self.last_chunk is not None:
            mcrow = self._get_or_create_mcrow(self.last_chunk)
            mcrow.update(current_chunk)
            
            # Step 7: 改良版予測（複数候補）
            predicted_chunks = mcrow.predict_multi(self.alpha, self.beta)
            
            # 各候補についてプリフェッチ実行
            for predicted_chunk in predicted_chunks:
                prefetched_blocks = self._prefetch(predicted_chunk)
                if len(prefetched_blocks) > 0:
                    self.stats['prefetch_issued'] += 1
                    self.stats['prefetch_blocks_total'] += len(prefetched_blocks)
        
        # 今回のチャンクを記録
        self.last_chunk = current_chunk
        
        # 履歴記録（100アクセスごと）
        if self.stats['total_accesses'] % 100 == 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_accesses']
            self.stats['hit_rate_history'].append(hit_rate)
            
            if self.stats['prefetch_blocks_total'] > 0:
                accuracy = self.stats['prefetch_blocks_used'] / self.stats['prefetch_blocks_total']
                self.stats['prefetch_accuracy_history'].append(accuracy)


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
    
    def __init__(self, config, seed=None):
        self.config = config
        self.seed = seed
        if seed is not None:
            random.seed(seed)
    
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
        
        # プリフェッチ追跡（CluMPと同様）
        self.prefetched_blocks = set()
        self.prefetch_metadata = {}
        self.prefetch_window_counter = 0
        
        self.stats = {
            'total_accesses': 0,
            'cache_hits': 0,
            'prefetch_blocks_used': 0,
            'prefetch_blocks_wasted': 0,
            'prefetch_blocks_total': 0,
            'prefetch_issued': 0,
            'hit_rate_history': [],
            'prefetch_accuracy_history': []
        }
    
    def process_access(self, block_id):
        """単純な逐次先読み（プリフェッチ精度測定付き）"""
        self.stats['total_accesses'] += 1
        
        # プリフェッチ精度評価：このブロックがプリフェッチされていたかチェック
        if block_id in self.prefetched_blocks:
            self.stats['prefetch_blocks_used'] += 1
            self.prefetched_blocks.discard(block_id)
            if block_id in self.prefetch_metadata:
                del self.prefetch_metadata[block_id]
        
        # キャッシュ確認
        if block_id in self.cache:
            self.stats['cache_hits'] += 1
        else:
            self.cache.add(block_id)
            self.cache_lru.append(block_id)
            
            if len(self.cache) > self.config.CACHE_SIZE:
                oldest = self.cache_lru.pop(0)
                self.cache.discard(oldest)
                self._handle_cache_eviction(oldest)
        
        # 逐次性判定
        if self.last_block is not None and block_id == self.last_block + 1:
            self.sequential_count += 1
            # 逐次なら先読み
            self.prefetch_window_counter += 1
            prefetch_count = 0
            for i in range(1, 33):  # 128KB = 32ブロック
                prefetch_block = block_id + i
                if prefetch_block < self.config.TOTAL_BLOCKS:
                    if prefetch_block not in self.cache:
                        self.cache.add(prefetch_block)
                        self.cache_lru.append(prefetch_block)
                        
                        # プリフェッチ追跡
                        self.prefetched_blocks.add(prefetch_block)
                        self.prefetch_metadata[prefetch_block] = self.prefetch_window_counter
                        prefetch_count += 1
                        
                        if len(self.cache) > self.config.CACHE_SIZE:
                            oldest = self.cache_lru.pop(0)
                            self.cache.discard(oldest)
                            self._handle_cache_eviction(oldest)
            
            if prefetch_count > 0:
                self.stats['prefetch_issued'] += 1
                self.stats['prefetch_blocks_total'] += prefetch_count
        else:
            self.sequential_count = 0
        
        self.last_block = block_id
        
        # ヒット率履歴
        if self.stats['total_accesses'] % 100 == 0:
            hit_rate = self.stats['cache_hits'] / self.stats['total_accesses']
            self.stats['hit_rate_history'].append(hit_rate)
            
            # プリフェッチ精度履歴も記録
            if self.stats['prefetch_blocks_total'] > 0:
                accuracy = self.stats['prefetch_blocks_used'] / self.stats['prefetch_blocks_total']
                self.stats['prefetch_accuracy_history'].append(accuracy)
    
    def _handle_cache_eviction(self, block_id):
        """キャッシュから追い出されたブロックの処理"""
        if block_id in self.prefetched_blocks:
            # プリフェッチされたが使われずに追い出された
            self.stats['prefetch_blocks_wasted'] += 1
            self.prefetched_blocks.discard(block_id)
            if block_id in self.prefetch_metadata:
                del self.prefetch_metadata[block_id]
    
    def get_results(self):
        total = self.stats['total_accesses']
        if total == 0:
            return {}
        
        # プリフェッチ精度計算
        prefetch_total = self.stats['prefetch_blocks_total']
        prefetch_accuracy = (self.stats['prefetch_blocks_used'] / prefetch_total 
                            if prefetch_total > 0 else 0)
        
        # 残っているプリフェッチブロック（未使用）を無駄としてカウント
        remaining_prefetch = len(self.prefetched_blocks)
        total_wasted = self.stats['prefetch_blocks_wasted'] + remaining_prefetch
        
        return {
            'cache_hit_rate': self.stats['cache_hits'] / total,
            'prefetch_accuracy': prefetch_accuracy,
            'prefetch_blocks_used': self.stats['prefetch_blocks_used'],
            'prefetch_blocks_wasted': total_wasted,
            'prefetch_blocks_total': prefetch_total,
            'prefetch_issued': self.stats['prefetch_issued'],
            'hit_rate_history': self.stats['hit_rate_history'],
            'prefetch_accuracy_history': self.stats['prefetch_accuracy_history']
        }


# ================================================================================
# マルチ試行実行と統計分析
# ================================================================================

def run_single_trial(args):
    """
    単一試行を実行（並列処理用）
    
    引数:
        args: (config, trial_number) のタプル
    
    戻り値:
        (trial_number, clump_results, improved_results, baseline_results, workload_info)
    """
    config, trial_num = args
    seed = config.RANDOM_SEED_BASE + trial_num
    
    # ワークロード生成（シード固定で再現性確保）
    generator = WorkloadGenerator(config, seed=seed)
    workload = generator.generate()
    
    workload_info = {
        'unique_blocks': len(set(workload)),
        'unique_chunks': len(set(b // config.CHUNK_SIZE for b in workload)),
        'seed': seed
    }
    
    # CluMP（論文版）シミュレーション
    clump = CluMPSimulator(config)
    for block_id in workload:
        clump.process_access(block_id)
    clump_results = clump.get_results()
    
    # Improved CluMP（改良版）シミュレーション
    improved = ImprovedCluMPSimulator(config)
    for block_id in workload:
        improved.process_access(block_id)
    improved_results = improved.get_results()
    
    # ベースラインシミュレーション
    baseline = BaselineSimulator(config)
    for block_id in workload:
        baseline.process_access(block_id)
    baseline_results = baseline.get_results()
    
    return (trial_num, clump_results, improved_results, baseline_results, workload_info)


def run_multiple_trials(config):
    """
    複数試行を実行（CPU並列化対応、進捗表示付き）
    
    引数:
        config: SimulatorConfig インスタンス
    
    戻り値:
        all_results: 各試行の結果リスト
    """
    num_trials = config.NUM_TRIALS
    
    print(f"\n[マルチ試行実行: {num_trials}回]")
    
    if config.USE_PARALLEL and num_trials > 1:
        # 並列実行（進捗表示付き）
        max_workers = config.MAX_WORKERS if config.MAX_WORKERS else min(num_trials, cpu_count())
        print(f"CPU並列処理を使用: {max_workers}ワーカー（CPUコア数: {cpu_count()}）")
        print(f"並列実行中... (最大{max_workers}試行が同時に実行されます)")
        
        args_list = [(config, i) for i in range(num_trials)]
        results = []
        
        import time
        start_time = time.time()
        
        with Pool(processes=max_workers) as pool:
            # imap()で完了した試行から順次受け取る
            for idx, result in enumerate(pool.imap(run_single_trial, args_list), 1):
                results.append(result)
                elapsed = time.time() - start_time
                avg_time = elapsed / idx
                remaining = (num_trials - idx) * avg_time
                
                print(f"  ✓ 試行 {idx}/{num_trials} 完了 "
                      f"(経過: {elapsed:.1f}秒, 推定残り: {remaining:.1f}秒)")
        
        total_time = time.time() - start_time
        print(f"✓ 全{num_trials}試行完了（並列実行、合計: {total_time:.1f}秒）")
    else:
        # 逐次実行
        if num_trials > 1:
            print("逐次実行モード（並列処理無効）")
        
        import time
        start_time = time.time()
        results = []
        
        for i in range(num_trials):
            trial_start = time.time()
            print(f"  試行 {i+1}/{num_trials} 実行中...")
            result = run_single_trial((config, i))
            results.append(result)
            
            trial_time = time.time() - trial_start
            elapsed = time.time() - start_time
            avg_time = elapsed / (i + 1)
            remaining = (num_trials - i - 1) * avg_time
            
            print(f"  ✓ 試行 {i+1} 完了 ({trial_time:.1f}秒, 推定残り: {remaining:.1f}秒)")
    
    return results


def calculate_statistics(all_results):
    """
    複数試行の結果から統計量を計算
    
    引数:
        all_results: run_multiple_trials()の戻り値
    
    戻り値:
        statistics: 統計情報を含む辞書
    """
    num_trials = len(all_results)
    
    # 各手法の結果を集約
    clump_hit_rates = []
    clump_prefetch_acc = []
    improved_hit_rates = []
    improved_prefetch_acc = []
    baseline_hit_rates = []
    baseline_prefetch_acc = []
    
    for trial_num, clump_res, improved_res, baseline_res, wl_info in all_results:
        clump_hit_rates.append(clump_res['cache_hit_rate'])
        clump_prefetch_acc.append(clump_res['prefetch_accuracy'])
        improved_hit_rates.append(improved_res['cache_hit_rate'])
        improved_prefetch_acc.append(improved_res['prefetch_accuracy'])
        baseline_hit_rates.append(baseline_res['cache_hit_rate'])
        baseline_prefetch_acc.append(baseline_res['prefetch_accuracy'])
    
    def compute_stats(values):
        """平均、標準偏差、95%信頼区間を計算"""
        arr = np.array(values)
        mean = np.mean(arr)
        std = np.std(arr, ddof=1) if len(arr) > 1 else 0.0
        
        if len(arr) > 1:
            # 95%信頼区間（t分布）
            confidence = 0.95
            dof = len(arr) - 1
            t_value = scipy_stats.t.ppf((1 + confidence) / 2, dof)
            margin = t_value * (std / np.sqrt(len(arr)))
            ci_lower = mean - margin
            ci_upper = mean + margin
        else:
            ci_lower = mean
            ci_upper = mean
        
        return {
            'mean': float(mean),
            'std': float(std),
            'min': float(np.min(arr)),
            'max': float(np.max(arr)),
            'ci_lower': float(ci_lower),
            'ci_upper': float(ci_upper)
        }
    
    statistics = {
        'num_trials': num_trials,
        'clump': {
            'hit_rate': compute_stats(clump_hit_rates),
            'prefetch_accuracy': compute_stats(clump_prefetch_acc)
        },
        'improved': {
            'hit_rate': compute_stats(improved_hit_rates),
            'prefetch_accuracy': compute_stats(improved_prefetch_acc)
        },
        'baseline': {
            'hit_rate': compute_stats(baseline_hit_rates),
            'prefetch_accuracy': compute_stats(baseline_prefetch_acc)
        },
        'raw_data': {
            'clump_hit_rates': clump_hit_rates,
            'clump_prefetch_acc': clump_prefetch_acc,
            'improved_hit_rates': improved_hit_rates,
            'improved_prefetch_acc': improved_prefetch_acc,
            'baseline_hit_rates': baseline_hit_rates,
            'baseline_prefetch_acc': baseline_prefetch_acc
        }
    }
    
    return statistics


def save_results_with_statistics(config, statistics, all_results, output_dir):
    """
    統計分析結果を含めて保存
    
    引数:
        config: SimulatorConfig
        statistics: calculate_statistics()の戻り値
        all_results: run_multiple_trials()の戻り値
        output_dir: 出力ディレクトリ
    """
    # 出力ディレクトリ作成
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # タイムスタンプ付きサブディレクトリ
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = output_path / f"session_{timestamp}_trials{statistics['num_trials']}"
    session_dir.mkdir(exist_ok=True)
    
    # === 1. JSON保存（統計データ含む） ===
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
            'sequential_ratio': config.SEQUENTIAL_RATIO,
            'alpha_threshold': config.ALPHA_THRESHOLD,
            'beta_threshold': config.BETA_THRESHOLD,
            'num_trials': config.NUM_TRIALS,
            'random_seed_base': config.RANDOM_SEED_BASE,
            'use_parallel': config.USE_PARALLEL
        },
        'statistics': statistics,
        'all_trials': [
            {
                'trial': trial_num,
                'clump': clump_res,
                'improved': improved_res,
                'baseline': baseline_res,
                'workload_info': wl_info
            }
            for trial_num, clump_res, improved_res, baseline_res, wl_info in all_results
        ]
    }
    
    with open(session_dir / 'results.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # === 2. テキストレポート ===
    with open(session_dir / 'summary.txt', 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("CluMP Simulator - マルチ試行実行結果サマリ\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("[設定]\n")
        f.write(f"総ブロック数: {config.TOTAL_BLOCKS:,} ({config.TOTAL_BLOCKS * 4 / 1024:.1f} MB)\n")
        f.write(f"チャンクサイズ: {config.CHUNK_SIZE} ブロック\n")
        f.write(f"クラスタサイズ: {config.CLUSTER_SIZE} チャンク\n")
        f.write(f"キャッシュサイズ: {config.CACHE_SIZE:,} ブロック ({config.CACHE_SIZE * 4 / 1024:.1f} MB)\n")
        f.write(f"プリフェッチウィンドウ: {config.PREFETCH_WINDOW_SIZE} ブロック\n")
        f.write(f"ワークロード: {config.WORKLOAD_TYPE}, {config.WORKLOAD_SIZE:,} アクセス\n")
        f.write(f"試行回数: {statistics['num_trials']}\n")
        f.write(f"並列処理: {'有効' if config.USE_PARALLEL else '無効'}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("=== キャッシュヒット率（統計）===\n")
        f.write("=" * 80 + "\n\n")
        
        def write_stats(name, stats_dict):
            s = stats_dict['hit_rate']
            f.write(f"{name}:\n")
            f.write(f"  平均値: {s['mean']:.4f} ({s['mean']*100:.2f}%)\n")
            f.write(f"  標準偏差: {s['std']:.4f} ({s['std']*100:.2f}%)\n")
            f.write(f"  95%信頼区間: [{s['ci_lower']:.4f}, {s['ci_upper']:.4f}]\n")
            f.write(f"  最小値: {s['min']:.4f}, 最大値: {s['max']:.4f}\n\n")
        
        write_stats("Baseline (Linux ReadAhead)", statistics['baseline'])
        write_stats("CluMP (Original)", statistics['clump'])
        write_stats("Improved CluMP", statistics['improved'])
        
        f.write("=" * 80 + "\n")
        f.write("=== プリフェッチ精度（統計）===\n")
        f.write("=" * 80 + "\n\n")
        
        def write_prefetch_stats(name, stats_dict):
            s = stats_dict['prefetch_accuracy']
            f.write(f"{name}:\n")
            f.write(f"  平均値: {s['mean']:.4f} ({s['mean']*100:.2f}%)\n")
            f.write(f"  標準偏差: {s['std']:.4f} ({s['std']*100:.2f}%)\n")
            f.write(f"  95%信頼区間: [{s['ci_lower']:.4f}, {s['ci_upper']:.4f}]\n")
            f.write(f"  最小値: {s['min']:.4f}, 最大値: {s['max']:.4f}\n\n")
        
        write_prefetch_stats("Baseline (Linux ReadAhead)", statistics['baseline'])
        write_prefetch_stats("CluMP (Original)", statistics['clump'])
        write_prefetch_stats("Improved CluMP", statistics['improved'])
        
        f.write("=" * 80 + "\n")
        f.write("=== 改善率（平均値）===\n")
        f.write("=" * 80 + "\n")
        
        clump_mean = statistics['clump']['hit_rate']['mean']
        improved_mean = statistics['improved']['hit_rate']['mean']
        baseline_mean = statistics['baseline']['hit_rate']['mean']
        
        if baseline_mean > 0:
            imp_c_vs_b = clump_mean / baseline_mean
            imp_i_vs_b = improved_mean / baseline_mean
            f.write(f"CluMP vs Baseline:   {imp_c_vs_b:.3f}x ({(imp_c_vs_b - 1) * 100:+.1f}%)\n")
            f.write(f"Improved vs Baseline: {imp_i_vs_b:.3f}x ({(imp_i_vs_b - 1) * 100:+.1f}%)\n")
        
        if clump_mean > 0:
            imp_i_vs_c = improved_mean / clump_mean
            f.write(f"Improved vs CluMP:    {imp_i_vs_c:.3f}x ({(imp_i_vs_c - 1) * 100:+.1f}%)\n")
    
    # === 3. グラフ生成（エラーバー付き） ===
    if config.SAVE_GRAPHS:
        # ヒット率比較（エラーバー付き）
        fig, ax = plt.subplots(figsize=(12, 6))
        methods = ['Linux ReadAhead', 'CluMP (Original)', 'Improved CluMP']
        means = [
            statistics['baseline']['hit_rate']['mean'],
            statistics['clump']['hit_rate']['mean'],
            statistics['improved']['hit_rate']['mean']
        ]
        stds = [
            statistics['baseline']['hit_rate']['std'],
            statistics['clump']['hit_rate']['std'],
            statistics['improved']['hit_rate']['std']
        ]
        colors = ['#ff7f0e', '#1f77b4', '#2ca02c']
        
        bars = ax.bar(methods, means, yerr=stds, capsize=10, color=colors, alpha=0.8)
        ax.set_ylabel('Cache Hit Rate')
        ax.set_title(f'Cache Hit Rate Comparison (n={statistics["num_trials"]} trials, mean ± std)')
        ax.set_ylim(0, 1.0)
        
        for i, (m, s) in enumerate(zip(means, stds)):
            ax.text(i, m + s + 0.02, f'{m:.2%}\n±{s:.2%}', ha='center', fontweight='bold', fontsize=9)
        
        plt.tight_layout()
        plt.savefig(session_dir / 'hit_rate_comparison.png', dpi=150)
        plt.close()
        
        # プリフェッチ精度比較（エラーバー付き）
        fig, ax = plt.subplots(figsize=(12, 6))
        means = [
            statistics['baseline']['prefetch_accuracy']['mean'],
            statistics['clump']['prefetch_accuracy']['mean'],
            statistics['improved']['prefetch_accuracy']['mean']
        ]
        stds = [
            statistics['baseline']['prefetch_accuracy']['std'],
            statistics['clump']['prefetch_accuracy']['std'],
            statistics['improved']['prefetch_accuracy']['std']
        ]
        
        bars = ax.bar(methods, means, yerr=stds, capsize=10, color=colors, alpha=0.8)
        ax.set_ylabel('Prefetch Accuracy')
        ax.set_title(f'Prefetch Accuracy Comparison (n={statistics["num_trials"]} trials, mean ± std)')
        ax.set_ylim(0, 1.0)
        
        for i, (m, s) in enumerate(zip(means, stds)):
            ax.text(i, m + s + 0.02, f'{m:.2%}\n±{s:.2%}', ha='center', fontweight='bold', fontsize=9)
        
        plt.tight_layout()
        plt.savefig(session_dir / 'prefetch_accuracy_comparison.png', dpi=150)
        plt.close()
        
        # 箱ひげ図（ヒット率）
        if statistics['num_trials'] >= 3:
            fig, ax = plt.subplots(figsize=(12, 6))
            data = [
                statistics['raw_data']['baseline_hit_rates'],
                statistics['raw_data']['clump_hit_rates'],
                statistics['raw_data']['improved_hit_rates']
            ]
            bp = ax.boxplot(data, labels=methods, patch_artist=True)
            
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.6)
            
            ax.set_ylabel('Cache Hit Rate')
            ax.set_title(f'Cache Hit Rate Distribution (n={statistics["num_trials"]} trials)')
            ax.set_ylim(0, 1.0)
            ax.grid(True, alpha=0.3, axis='y')
            
            plt.tight_layout()
            plt.savefig(session_dir / 'hit_rate_boxplot.png', dpi=150)
            plt.close()
    
    print(f"\n✓ 結果を保存しました: {session_dir}")
    return session_dir


# ================================================================================
# 結果の可視化と保存
# ================================================================================

def save_results(config, clump_results, improved_results, baseline_results, workload_info, output_dir):
    """結果をファイルとグラフで保存（3者比較版）"""
    
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
            'sequential_ratio': config.SEQUENTIAL_RATIO,
            'alpha_threshold': config.ALPHA_THRESHOLD,
            'beta_threshold': config.BETA_THRESHOLD
        },
        'clump_results': clump_results,
        'improved_clump_results': improved_results,
        'baseline_results': baseline_results,
        'workload_info': workload_info,
        'improvement': {
            'clump_vs_baseline': clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate']
            if baseline_results['cache_hit_rate'] > 0 else 0,
            'improved_vs_baseline': improved_results['cache_hit_rate'] / baseline_results['cache_hit_rate']
            if baseline_results['cache_hit_rate'] > 0 else 0,
            'improved_vs_clump': improved_results['cache_hit_rate'] / clump_results['cache_hit_rate']
            if clump_results['cache_hit_rate'] > 0 else 0
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
        
        f.write("[CluMP (論文版) 結果]\n")
        f.write(f"キャッシュヒット率: {clump_results['cache_hit_rate']:.2%}\n")
        f.write(f"プリフェッチ精度: {clump_results['prefetch_accuracy']:.2%}\n")
        f.write(f"  - 使用されたブロック: {clump_results['prefetch_blocks_used']:,}\n")
        f.write(f"  - 無駄だったブロック: {clump_results['prefetch_blocks_wasted']:,}\n")
        f.write(f"  - 総プリフェッチブロック: {clump_results['prefetch_blocks_total']:,}\n")
        f.write(f"プリフェッチ実行回数: {clump_results['prefetch_issued']:,}\n")
        f.write(f"MCRow数: {clump_results['mcrow_count']:,}\n")
        f.write(f"メモリ使用量: {clump_results['memory_usage_kb']:.2f} KB\n\n")
        
        f.write("[Improved CluMP (改良版) 結果]\n")
        f.write(f"キャッシュヒット率: {improved_results['cache_hit_rate']:.2%}\n")
        f.write(f"プリフェッチ精度: {improved_results['prefetch_accuracy']:.2%}\n")
        f.write(f"  - 使用されたブロック: {improved_results['prefetch_blocks_used']:,}\n")
        f.write(f"  - 無駄だったブロック: {improved_results['prefetch_blocks_wasted']:,}\n")
        f.write(f"  - 総プリフェッチブロック: {improved_results['prefetch_blocks_total']:,}\n")
        f.write(f"プリフェッチ実行回数: {improved_results['prefetch_issued']:,}\n")
        f.write(f"MCRow数: {improved_results['mcrow_count']:,}\n")
        f.write(f"メモリ使用量: {improved_results['memory_usage_kb']:.2f} KB\n\n")
        
        f.write("[Baseline (Linux ReadAhead) 結果]\n")
        f.write(f"キャッシュヒット率: {baseline_results['cache_hit_rate']:.2%}\n")
        f.write(f"プリフェッチ精度: {baseline_results['prefetch_accuracy']:.2%}\n")
        f.write(f"  - 使用されたブロック: {baseline_results['prefetch_blocks_used']:,}\n")
        f.write(f"  - 無駄だったブロック: {baseline_results['prefetch_blocks_wasted']:,}\n")
        f.write(f"  - 総プリフェッチブロック: {baseline_results['prefetch_blocks_total']:,}\n")
        f.write(f"プリフェッチ実行回数: {baseline_results['prefetch_issued']:,}\n\n")
        
        f.write("[改善率]\n")
        imp_c_vs_b = clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
        imp_i_vs_b = improved_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
        imp_i_vs_c = improved_results['cache_hit_rate'] / clump_results['cache_hit_rate'] if clump_results['cache_hit_rate'] > 0 else 0
        f.write(f"CluMP vs Baseline: {imp_c_vs_b:.2f}x ({imp_c_vs_b * 100 - 100:+.1f}%)\n")
        f.write(f"Improved vs Baseline: {imp_i_vs_b:.2f}x ({imp_i_vs_b * 100 - 100:+.1f}%)\n")
        f.write(f"Improved vs CluMP: {imp_i_vs_c:.2f}x ({imp_i_vs_c * 100 - 100:+.1f}%)\n")
    
    # === 2. グラフ生成 ===
    if config.SAVE_GRAPHS:
        # ヒット率比較（3者）
        fig, ax = plt.subplots(figsize=(12, 6))
        methods = ['Linux ReadAhead', 'CluMP (Original)', 'Improved CluMP']
        values = [baseline_results['cache_hit_rate'], 
                 clump_results['cache_hit_rate'], 
                 improved_results['cache_hit_rate']]
        colors = ['#ff7f0e', '#1f77b4', '#2ca02c']
        
        ax.bar(methods, values, color=colors)
        ax.set_ylabel('Cache Hit Rate')
        ax.set_title('Cache Hit Rate Comparison: Baseline vs CluMP vs Improved CluMP')
        ax.set_ylim(0, 1.0)
        for i, v in enumerate(values):
            ax.text(i, v + 0.02, f'{v:.2%}', ha='center', fontweight='bold')
        plt.tight_layout()
        plt.savefig(session_dir / 'hit_rate_comparison.png', dpi=150)
        plt.close()
        
        # プリフェッチ精度比較（3者）
        fig, ax = plt.subplots(figsize=(12, 6))
        methods = ['Linux ReadAhead', 'CluMP (Original)', 'Improved CluMP']
        values = [baseline_results['prefetch_accuracy'], 
                 clump_results['prefetch_accuracy'], 
                 improved_results['prefetch_accuracy']]
        colors = ['#ff7f0e', '#1f77b4', '#2ca02c']
        
        ax.bar(methods, values, color=colors)
        ax.set_ylabel('Prefetch Accuracy')
        ax.set_title('Prefetch Accuracy Comparison: Baseline vs CluMP vs Improved CluMP')
        ax.set_ylim(0, 1.0)
        for i, v in enumerate(values):
            ax.text(i, v + 0.02, f'{v:.2%}', ha='center', fontweight='bold')
        plt.tight_layout()
        plt.savefig(session_dir / 'prefetch_accuracy_comparison.png', dpi=150)
        plt.close()
        
        # ヒット率推移（3者）
        fig, ax = plt.subplots(figsize=(12, 6))
        x_clump = list(range(len(clump_results['hit_rate_history'])))
        x_improved = list(range(len(improved_results['hit_rate_history'])))
        x_baseline = list(range(len(baseline_results['hit_rate_history'])))
        
        ax.plot(x_baseline, baseline_results['hit_rate_history'], 
               label='Linux ReadAhead', linewidth=2, color='#ff7f0e')
        ax.plot(x_clump, clump_results['hit_rate_history'], 
               label='CluMP (Original)', linewidth=2, color='#1f77b4')
        ax.plot(x_improved, improved_results['hit_rate_history'], 
               label='Improved CluMP', linewidth=2, color='#2ca02c')
        
        ax.set_xlabel('Time (×100 accesses)')
        ax.set_ylabel('Cache Hit Rate')
        ax.set_title('Hit Rate Progression Over Time')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(session_dir / 'hit_rate_progression.png', dpi=150)
        plt.close()
        
        # プリフェッチ精度推移（3者）
        if (len(clump_results['prefetch_accuracy_history']) > 0 or 
            len(improved_results['prefetch_accuracy_history']) > 0 or 
            len(baseline_results['prefetch_accuracy_history']) > 0):
            fig, ax = plt.subplots(figsize=(12, 6))
            
            if len(baseline_results['prefetch_accuracy_history']) > 0:
                x_baseline = list(range(len(baseline_results['prefetch_accuracy_history'])))
                ax.plot(x_baseline, baseline_results['prefetch_accuracy_history'], 
                       label='Linux ReadAhead', linewidth=2, color='#ff7f0e')
            
            if len(clump_results['prefetch_accuracy_history']) > 0:
                x_clump = list(range(len(clump_results['prefetch_accuracy_history'])))
                ax.plot(x_clump, clump_results['prefetch_accuracy_history'], 
                       label='CluMP (Original)', linewidth=2, color='#1f77b4')
            
            if len(improved_results['prefetch_accuracy_history']) > 0:
                x_improved = list(range(len(improved_results['prefetch_accuracy_history'])))
                ax.plot(x_improved, improved_results['prefetch_accuracy_history'], 
                       label='Improved CluMP', linewidth=2, color='#2ca02c')
            
            ax.set_xlabel('Time (×100 accesses)')
            ax.set_ylabel('Prefetch Accuracy')
            ax.set_title('Prefetch Accuracy Progression Over Time')
            ax.set_ylim(0, 1.0)
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(session_dir / 'prefetch_accuracy_progression.png', dpi=150)
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
    print("CluMP Simulator - 論文完全準拠版（CPU並列化対応）")
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
    print(f"試行回数: {config.NUM_TRIALS}")
    
    # マルチ試行モード判定
    if config.NUM_TRIALS > 1:
        # === マルチ試行モード ===
        print(f"\n{'='*80}")
        print(f"マルチ試行モード: {config.NUM_TRIALS}回の試行で統計分析")
        print(f"{'='*80}")
        
        import time
        start_time = time.time()
        
        # 複数試行実行
        all_results = run_multiple_trials(config)
        
        elapsed_time = time.time() - start_time
        print(f"\n実行時間: {elapsed_time:.1f}秒 ({elapsed_time/60:.1f}分)")
        print(f"1試行あたり: {elapsed_time/config.NUM_TRIALS:.1f}秒")
        
        # 統計分析
        print("\n[統計分析中...]")
        statistics = calculate_statistics(all_results)
        
        # 結果表示
        print("\n" + "=" * 80)
        print("=== キャッシュヒット率（統計）===")
        print("=" * 80)
        
        def print_stats(name, stats_dict):
            s = stats_dict['hit_rate']
            print(f"\n{name}:")
            print(f"  平均値: {s['mean']:.4f} ({s['mean']*100:.2f}%)")
            print(f"  標準偏差: {s['std']:.4f} ({s['std']*100:.2f}%)")
            print(f"  95%信頼区間: [{s['ci_lower']:.4f}, {s['ci_upper']:.4f}]")
            print(f"  範囲: [{s['min']:.4f}, {s['max']:.4f}]")
        
        print_stats("Baseline (Linux ReadAhead)", statistics['baseline'])
        print_stats("CluMP (Original)", statistics['clump'])
        print_stats("Improved CluMP", statistics['improved'])
        
        print("\n" + "=" * 80)
        print("=== プリフェッチ精度（統計）===")
        print("=" * 80)
        
        def print_prefetch_stats(name, stats_dict):
            s = stats_dict['prefetch_accuracy']
            print(f"\n{name}:")
            print(f"  平均値: {s['mean']:.4f} ({s['mean']*100:.2f}%)")
            print(f"  標準偏差: {s['std']:.4f} ({s['std']*100:.2f}%)")
            print(f"  95%信頼区間: [{s['ci_lower']:.4f}, {s['ci_upper']:.4f}]")
        
        print_prefetch_stats("Baseline (Linux ReadAhead)", statistics['baseline'])
        print_prefetch_stats("CluMP (Original)", statistics['clump'])
        print_prefetch_stats("Improved CluMP", statistics['improved'])
        
        # 結果保存
        print("\n[結果保存中...]")
        output_dir = save_results_with_statistics(config, statistics, all_results, config.OUTPUT_DIR)
        
    else:
        # === シングル試行モード（従来の動作） ===
        print("\nシングル試行モード")
        
        # ワークロード生成
        print("\n[ワークロード生成中...]")
        generator = WorkloadGenerator(config, seed=config.RANDOM_SEED_BASE)
        workload = generator.generate()
        
        workload_info = {
            'unique_blocks': len(set(workload)),
            'unique_chunks': len(set(b // config.CHUNK_SIZE for b in workload))
        }
        print(f"✓ {len(workload):,} アクセス生成完了")
        print(f"  - ユニークブロック数: {workload_info['unique_blocks']:,}")
        print(f"  - ユニークチャンク数: {workload_info['unique_chunks']:,}")
        
        # CluMP（論文版）シミュレーション
        print("\n[CluMP (Original) シミュレーション実行中...]")
        clump = CluMPSimulator(config)
        for i, block_id in enumerate(workload):
            clump.process_access(block_id)
            if config.VERBOSE_LOG and (i + 1) % 1000 == 0:
                print(f"  進捗: {i + 1:,} / {len(workload):,} ({(i + 1) / len(workload) * 100:.1f}%)")
        
        clump_results = clump.get_results()
        print(f"✓ 完了 - ヒット率: {clump_results['cache_hit_rate']:.2%}")
        
        # Improved CluMP（改良版）シミュレーション
        print(f"\n[Improved CluMP シミュレーション実行中...]")
        print(f"  パラメータ: α={config.ALPHA_THRESHOLD}, β={config.BETA_THRESHOLD}")
        improved = ImprovedCluMPSimulator(config)
        for i, block_id in enumerate(workload):
            improved.process_access(block_id)
            if config.VERBOSE_LOG and (i + 1) % 1000 == 0:
                print(f"  進捗: {i + 1:,} / {len(workload):,} ({(i + 1) / len(workload) * 100:.1f}%)")
        
        improved_results = improved.get_results()
        print(f"✓ 完了 - ヒット率: {improved_results['cache_hit_rate']:.2%}")
        
        # ベースラインシミュレーション
        print("\n[Baseline (Linux ReadAhead) シミュレーション実行中...]")
        baseline = BaselineSimulator(config)
        for i, block_id in enumerate(workload):
            baseline.process_access(block_id)
        
        baseline_results = baseline.get_results()
        print(f"✓ 完了 - ヒット率: {baseline_results['cache_hit_rate']:.2%}")
        
        # 結果比較（3者）
        print("\n[結果比較]")
        print("\n" + "=" * 80)
        print("=== キャッシュヒット率 ===")
        print("=" * 80)
        print(f"Baseline (Linux RA):   {baseline_results['cache_hit_rate']:.2%}")
        print(f"CluMP (Original):      {clump_results['cache_hit_rate']:.2%}")
        print(f"Improved CluMP:        {improved_results['cache_hit_rate']:.2%}")
        
        imp_c_vs_b = clump_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
        imp_i_vs_b = improved_results['cache_hit_rate'] / baseline_results['cache_hit_rate'] if baseline_results['cache_hit_rate'] > 0 else 0
        imp_i_vs_c = improved_results['cache_hit_rate'] / clump_results['cache_hit_rate'] if clump_results['cache_hit_rate'] > 0 else 0
        
        print(f"\n改善率:")
        print(f"  CluMP vs Baseline:   {imp_c_vs_b:.3f}x ({imp_c_vs_b * 100 - 100:+.1f}%)")
        print(f"  Improved vs Baseline: {imp_i_vs_b:.3f}x ({imp_i_vs_b * 100 - 100:+.1f}%)")
        print(f"  Improved vs CluMP:    {imp_i_vs_c:.3f}x ({imp_i_vs_c * 100 - 100:+.1f}%)")
        
        print("\n" + "=" * 80)
        print("=== プリフェッチ精度 ===")
        print("=" * 80)
        print(f"Baseline (Linux RA):   {baseline_results['prefetch_accuracy']:.2%}")
        print(f"CluMP (Original):      {clump_results['prefetch_accuracy']:.2%}")
        print(f"Improved CluMP:        {improved_results['prefetch_accuracy']:.2%}")
        
        print("\n" + "=" * 80)
        print("=== 詳細統計 ===")
        print("=" * 80)
        print(f"\n【CluMP (Original)】")
        print(f"  プリフェッチ使用/無駄/総: {clump_results['prefetch_blocks_used']:,} / {clump_results['prefetch_blocks_wasted']:,} / {clump_results['prefetch_blocks_total']:,}")
        print(f"  プリフェッチ実行回数: {clump_results['prefetch_issued']:,}")
        print(f"  MCRow数: {clump_results['mcrow_count']:,}, メモリ: {clump_results['memory_usage_kb']:.2f} KB")
        
        print(f"\n【Improved CluMP】")
        print(f"  プリフェッチ使用/無駄/総: {improved_results['prefetch_blocks_used']:,} / {improved_results['prefetch_blocks_wasted']:,} / {improved_results['prefetch_blocks_total']:,}")
        print(f"  プリフェッチ実行回数: {improved_results['prefetch_issued']:,}")
        print(f"  MCRow数: {improved_results['mcrow_count']:,}, メモリ: {improved_results['memory_usage_kb']:.2f} KB")
        
        print(f"\n【Baseline (Linux RA)】")
        print(f"  プリフェッチ使用/無駄/総: {baseline_results['prefetch_blocks_used']:,} / {baseline_results['prefetch_blocks_wasted']:,} / {baseline_results['prefetch_blocks_total']:,}")
        print(f"  プリフェッチ実行回数: {baseline_results['prefetch_issued']:,}")
        
        # 結果保存
        print("\n[結果保存中...]")
        output_dir = save_results(config, clump_results, improved_results, baseline_results, workload_info, config.OUTPUT_DIR)
    
    print("\n" + "=" * 80)
    print("シミュレーション完了")
    print("=" * 80)


if __name__ == "__main__":
    main()
