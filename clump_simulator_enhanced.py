#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP Enhanced Implementation with Improved Learning and Prefetching
論文準拠CluMP改良版 - 学習効果とプリフェッチ精度の向上

主要改善点:
1. MC学習アルゴリズムの最適化
2. プリフェッチ戦略の改善  
3. キャッシュ管理の最適化
4. ワークロード特性に応じた適応的パラメータ
"""

from collections import OrderedDict
import logging
import random
import time
import math
from typing import List, Dict, Tuple, Optional, Any, Union

# ログ設定
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')


class EnhancedLRUCache:
    """
    強化版LRUキャッシュ
    
    プリフェッチ追跡とヒット率最適化を改善
    """
    
    def __init__(self, cache_size_blocks: int):
        if cache_size_blocks <= 0:
            raise ValueError("キャッシュサイズは正の値である必要があります")
            
        self.cache_size = cache_size_blocks
        # (is_prefetched, was_used_after_prefetch, access_count)
        self.cache: OrderedDict[int, Tuple[bool, bool, int]] = OrderedDict()
        
        # 詳細プリフェッチ統計
        self.prefetch_stats = {
            "prefetch_total": 0,
            "prefetch_used": 0,
            "prefetch_unused": 0,
            "prefetch_hit": 0,        # プリフェッチブロックへの直接ヒット
            "demand_hit": 0,          # 通常アクセスでのヒット
            "total_accesses": 0
        }
    
    def access(self, block_id: int) -> bool:
        """強化版ブロックアクセス処理"""
        self.prefetch_stats["total_accesses"] += 1
        
        if block_id in self.cache:
            is_prefetched, was_used, access_count = self.cache[block_id]
            
            # アクセス統計更新
            if is_prefetched:
                if not was_used:
                    self.prefetch_stats["prefetch_used"] += 1
                    was_used = True
                self.prefetch_stats["prefetch_hit"] += 1
            else:
                self.prefetch_stats["demand_hit"] += 1
            
            # LRU順序更新
            self.cache[block_id] = (is_prefetched, was_used, access_count + 1)
            self.cache.move_to_end(block_id)
            
            return True
        
        return False
    
    def insert(self, block_id: int, is_prefetch: bool = False) -> None:
        """強化版ブロック挿入"""
        if block_id in self.cache:
            _, was_used, access_count = self.cache[block_id]
            self.cache[block_id] = (is_prefetch, was_used, access_count)
            self.cache.move_to_end(block_id)
            return
        
        # キャッシュ満杯時のエビクション
        if len(self.cache) >= self.cache_size:
            lru_block, (was_prefetched, was_used, _) = self.cache.popitem(last=False)
            
            if was_prefetched and not was_used:
                self.prefetch_stats["prefetch_unused"] += 1
        
        # 新ブロック挿入
        self.cache[block_id] = (is_prefetch, False, 0)
        
        if is_prefetch:
            self.prefetch_stats["prefetch_total"] += 1
    
    def get_hit_rate(self) -> float:
        """総合ヒット率を計算"""
        total_hits = self.prefetch_stats["prefetch_hit"] + self.prefetch_stats["demand_hit"]
        total_accesses = self.prefetch_stats["total_accesses"]
        return total_hits / total_accesses if total_accesses > 0 else 0.0
    
    def get_prefetch_efficiency(self) -> float:
        """プリフェッチ効率を計算"""
        total = self.prefetch_stats["prefetch_total"]
        used = self.prefetch_stats["prefetch_used"]
        return used / total if total > 0 else 0.0


class EnhancedMCRow:
    """
    強化版MCRow - 学習効果と予測精度を改善
    
    改善点:
    1. 適応的信頼度スコア
    2. 時間重み付き学習
    3. 予測精度の動的評価
    """
    
    def __init__(self):
        # 基本構造（論文準拠）
        self.CN1: int = -1
        self.CN2: int = -1  
        self.CN3: int = -1
        self.P1: int = 0
        self.P2: int = 0
        self.P3: int = 0
        
        # 強化機能
        self._last_update_time = {1: 0, 2: 0, 3: 0}
        self._global_time = 0
        self._prediction_history = []  # 予測成功/失敗履歴
        self._confidence_threshold = 3  # 予測実行の最小信頼度
        
        # 適応的学習レート
        self._learning_rate = 1.0
        self._decay_factor = 0.99
    
    def update_transition(self, next_chunk_id: int) -> None:
        """強化版遷移更新"""
        self._global_time += 1
        
        # 予測が正しかったかチェック
        if self.CN1 >= 0:
            prediction_correct = (next_chunk_id == self.CN1)
            self._prediction_history.append(prediction_correct)
            
            # 履歴サイズ制限
            if len(self._prediction_history) > 50:
                self._prediction_history.pop(0)
            
            # 適応的学習レート調整
            if prediction_correct:
                self._learning_rate = min(self._learning_rate * 1.05, 2.0)
            else:
                self._learning_rate = max(self._learning_rate * 0.95, 0.5)
        
        # 重み付き頻度更新
        weight = max(1, int(self._learning_rate))
        
        # 既存チャンクの場合
        if next_chunk_id == self.CN1:
            self.P1 += weight
            self._last_update_time[1] = self._global_time
        elif next_chunk_id == self.CN2:
            self.P2 += weight
            self._last_update_time[2] = self._global_time
        elif next_chunk_id == self.CN3:
            self.P3 += weight
            self._last_update_time[3] = self._global_time
        else:
            # 新チャンクの場合
            self.CN3 = next_chunk_id
            self.P3 = weight
            self._last_update_time[3] = self._global_time
        
        # 時間減衰適用
        self._apply_time_decay()
        
        # ソート実行
        self._sort_candidates()
    
    def _apply_time_decay(self) -> None:
        """時間減衰を適用して古い遷移の影響を削減"""
        if self._global_time % 100 == 0:  # 100回に1回実行
            self.P1 = max(1, int(self.P1 * self._decay_factor)) if self.CN1 >= 0 else 0
            self.P2 = max(1, int(self.P2 * self._decay_factor)) if self.CN2 >= 0 else 0
            self.P3 = max(1, int(self.P3 * self._decay_factor)) if self.CN3 >= 0 else 0
    
    def _sort_candidates(self) -> None:
        """強化版候補ソート"""
        candidates = []
        
        if self.CN1 >= 0:
            candidates.append((self.CN1, self.P1, self._last_update_time[1], 1))
        if self.CN2 >= 0:
            candidates.append((self.CN2, self.P2, self._last_update_time[2], 2))
        if self.CN3 >= 0:
            candidates.append((self.CN3, self.P3, self._last_update_time[3], 3))
        
        # ソート：頻度降順、同値なら更新時刻降順
        candidates.sort(key=lambda x: (-x[1], -x[2]))
        
        # リセット
        self.CN1 = self.CN2 = self.CN3 = -1
        self.P1 = self.P2 = self.P3 = 0
        
        # 再割り当て
        for i, (chunk_id, freq, update_time, _) in enumerate(candidates):
            if i == 0:
                self.CN1, self.P1 = chunk_id, freq
                self._last_update_time[1] = update_time
            elif i == 1:
                self.CN2, self.P2 = chunk_id, freq
                self._last_update_time[2] = update_time
            elif i == 2:
                self.CN3, self.P3 = chunk_id, freq
                self._last_update_time[3] = update_time
    
    def predict_next_chunk(self) -> Optional[int]:
        """信頼度ベース予測"""
        if self.CN1 < 0 or self.P1 < self._confidence_threshold:
            return None
        
        # 予測精度が低い場合は予測を控える
        if len(self._prediction_history) > 10:
            recent_accuracy = sum(self._prediction_history[-10:]) / 10
            if recent_accuracy < 0.3:
                return None
        
        return self.CN1
    
    def get_prediction_confidence(self) -> float:
        """予測信頼度を取得"""
        if self.CN1 < 0:
            return 0.0
        
        total_freq = self.P1 + self.P2 + self.P3
        if total_freq == 0:
            return 0.0
        
        # 頻度ベース信頼度
        freq_confidence = self.P1 / total_freq
        
        # 履歴ベース信頼度
        hist_confidence = 0.5
        if len(self._prediction_history) > 5:
            hist_confidence = sum(self._prediction_history[-10:]) / min(10, len(self._prediction_history))
        
        return (freq_confidence + hist_confidence) / 2


class EnhancedCluMPSimulator:
    """
    強化版CluMPシミュレータ
    
    改善点:
    1. 適応的プリフェッチ窓サイズ
    2. 信頼度ベースプリフェッチ
    3. 学習期間の考慮
    4. プリフェッチ範囲の最適化
    """
    
    def __init__(self, chunk_size_blocks: int, cluster_size_chunks: int, 
                 cache_size_blocks: int, initial_prefetch_window: int = 16):
        # パラメータ検証
        if any(x <= 0 for x in [chunk_size_blocks, cluster_size_chunks, 
                                cache_size_blocks, initial_prefetch_window]):
            raise ValueError("すべてのパラメータは正の値である必要があります")
        
        self.chunk_size = chunk_size_blocks
        self.cluster_size = cluster_size_chunks
        self.cache_size = cache_size_blocks
        self.initial_prefetch_window = initial_prefetch_window
        
        # コンポーネント
        self.cache = EnhancedLRUCache(cache_size_blocks)
        self.clusters: Dict[int, Dict[int, EnhancedMCRow]] = {}
        
        # 適応的パラメータ
        self.current_prefetch_window = initial_prefetch_window
        self.min_prefetch_window = 4
        self.max_prefetch_window = 64
        
        # 統計
        self.total_accesses = 0
        self.cache_hits = 0
        self.previous_chunk_id: Optional[int] = None
        self.successful_predictions = 0
        self.total_predictions = 0
        
        # 学習フェーズ制御
        self.learning_phase_length = 1000  # 最初の1000アクセスは学習重視
        self.adaptive_prefetch_enabled = False
        
        logging.info(f"強化版CluMPシミュレータ初期化: chunk={chunk_size_blocks}, "
                    f"cluster={cluster_size_chunks}, cache={cache_size_blocks}")
    
    def _get_chunk_id(self, block_id: int) -> int:
        """ブロックIDからチャンクIDを計算"""
        return block_id // self.chunk_size
    
    def _get_mc_row(self, chunk_id: int, allocate: bool = False) -> Optional[EnhancedMCRow]:
        """MCRowを取得（動的割り当て）"""
        cluster_id = chunk_id // self.cluster_size
        chunk_in_cluster = chunk_id % self.cluster_size
        
        if cluster_id not in self.clusters:
            if not allocate:
                return None
            self.clusters[cluster_id] = {}
        
        if chunk_in_cluster not in self.clusters[cluster_id]:
            if not allocate:
                return None
            self.clusters[cluster_id][chunk_in_cluster] = EnhancedMCRow()
        
        return self.clusters[cluster_id][chunk_in_cluster]
    
    def _adaptive_prefetch_chunk(self, chunk_id: int, confidence: float) -> None:
        """適応的チャンクプリフェッチ"""
        start_block = chunk_id * self.chunk_size
        
        # 信頼度に基づく窓サイズ調整
        confidence_factor = min(confidence * 2, 1.0)
        effective_window = max(self.min_prefetch_window, 
                              int(self.current_prefetch_window * confidence_factor))
        
        prefetch_count = 0
        for i in range(effective_window):
            prefetch_block = start_block + i
            if not self.cache.access(prefetch_block):
                self.cache.insert(prefetch_block, is_prefetch=True)
                prefetch_count += 1
                
                # 適応的な範囲制限
                if prefetch_count >= self.max_prefetch_window:
                    break
    
    def _update_prefetch_window(self, prediction_success: bool) -> None:
        """プリフェッチ窓サイズの適応的調整"""
        if not self.adaptive_prefetch_enabled:
            return
        
        if prediction_success:
            # 成功時：窓サイズを少し増加
            self.current_prefetch_window = min(
                self.current_prefetch_window * 1.1,
                self.max_prefetch_window
            )
        else:
            # 失敗時：窓サイズを少し減少  
            self.current_prefetch_window = max(
                self.current_prefetch_window * 0.9,
                self.min_prefetch_window
            )
    
    def process_access(self, block_id: int) -> bool:
        """強化版ブロックアクセス処理"""
        self.total_accesses += 1
        current_chunk_id = self._get_chunk_id(block_id)
        
        # 学習フェーズ完了チェック
        if self.total_accesses == self.learning_phase_length:
            self.adaptive_prefetch_enabled = True
            logging.info("学習フェーズ完了、適応的プリフェッチ有効化")
        
        # キャッシュアクセス
        cache_hit = self.cache.access(block_id)
        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache.insert(block_id, is_prefetch=False)
        
        # MC更新と予測
        prediction_made = False
        prediction_success = False
        
        if self.previous_chunk_id is not None:
            # MC更新
            mc_row = self._get_mc_row(self.previous_chunk_id, allocate=True)
            mc_row.update_transition(current_chunk_id)
            
            # 現在チャンクからの予測実行
            current_mc_row = self._get_mc_row(current_chunk_id, allocate=False)
            if current_mc_row is not None:
                predicted_chunk = current_mc_row.predict_next_chunk()
                if predicted_chunk is not None:
                    confidence = current_mc_row.get_prediction_confidence()
                    
                    # 信頼度が十分高い場合のみプリフェッチ
                    if confidence > 0.4:  # 閾値調整
                        self._adaptive_prefetch_chunk(predicted_chunk, confidence)
                        prediction_made = True
                        self.total_predictions += 1
        
        # プリフェッチ窓サイズ調整
        if prediction_made:
            self._update_prefetch_window(prediction_success)
        
        self.previous_chunk_id = current_chunk_id
        return cache_hit
    
    def get_evaluation_metrics(self) -> Dict[str, Any]:
        """強化版評価指標"""
        hit_rate = self.cache.get_hit_rate()
        prefetch_efficiency = self.cache.get_prefetch_efficiency()
        
        # MC統計計算
        total_mc_rows = sum(len(cluster) for cluster in self.clusters.values())
        memory_usage = total_mc_rows * 24  # 24B per MCRow
        
        # 予測精度計算
        prediction_accuracy = 0.0
        if self.total_predictions > 0:
            prediction_accuracy = self.successful_predictions / self.total_predictions
        
        return {
            "total_accesses": self.total_accesses,
            "cache_hits": self.cache_hits,
            "hit_rate": hit_rate,
            "prefetch_total": self.cache.prefetch_stats["prefetch_total"],
            "prefetch_used": self.cache.prefetch_stats["prefetch_used"],
            "prefetch_unused": self.cache.prefetch_stats["prefetch_unused"],
            "prefetch_efficiency": prefetch_efficiency,
            "memory_usage_mc_rows": total_mc_rows,
            "memory_usage_bytes": memory_usage,
            "memory_usage_kb": memory_usage / 1024,
            "prediction_accuracy": prediction_accuracy,
            "current_prefetch_window": self.current_prefetch_window,
            "adaptive_enabled": self.adaptive_prefetch_enabled,
            "chunk_size": self.chunk_size,
            "cluster_size": self.cluster_size,
            "cache_size": self.cache_size,
        }


def enhanced_comparison_test():
    """強化版比較テスト"""
    print("🚀 CluMP強化版性能テスト")
    print("=" * 50)
    
    # 最適化パラメータ
    enhanced_params = {
        "chunk_size": 8,
        "cluster_size": 32,
        "initial_prefetch_window": 12
    }
    
    cache_size = 4096
    
    # より現実的なワークロード生成
    def generate_enhanced_kvm_workload(total_blocks: int = 12000) -> List[int]:
        trace = []
        # Phase 1: ブート逐次読み込み (高い局所性)
        base = random.randint(0, 10000)
        for i in range(total_blocks // 3):
            if random.random() < 0.9:  # 90% 逐次
                trace.append(base + i)
            else:
                base += random.randint(1, 10)
                trace.append(base)
        
        # Phase 2: 設定ファイル読み込み (中程度の局所性)
        for _ in range(total_blocks // 3):
            if random.random() < 0.6:  # 60% 局所的
                base += random.randint(1, 50)
                for j in range(random.randint(3, 15)):
                    trace.append(base + j)
            else:
                trace.append(random.randint(0, 100000))
        
        # Phase 3: アプリケーション読み込み (低い局所性)
        for _ in range(total_blocks - len(trace)):
            pattern = random.random()
            if pattern < 0.4:
                trace.append(base + random.randint(1, 100))
            elif pattern < 0.7:
                base += random.randint(100, 1000)
                trace.append(base)
            else:
                trace.append(random.randint(0, 200000))
        
        return trace
    
    # テスト実行
    trace = generate_enhanced_kvm_workload()
    
    # 強化版CluMP
    enhanced_clump = EnhancedCluMPSimulator(
        chunk_size_blocks=enhanced_params["chunk_size"],
        cluster_size_chunks=enhanced_params["cluster_size"],
        cache_size_blocks=cache_size,
        initial_prefetch_window=enhanced_params["initial_prefetch_window"]
    )
    
    for block_id in trace:
        enhanced_clump.process_access(block_id)
    
    enhanced_results = enhanced_clump.get_evaluation_metrics()
    
    # Linux先読み（比較用）
    from clump_simulator import LinuxReadAhead
    readahead = LinuxReadAhead(cache_size_blocks=cache_size)
    
    for block_id in trace:
        readahead.process_access(block_id)
    
    readahead_results = readahead.get_evaluation_metrics()
    
    # 結果表示
    print(f"📊 結果比較")
    print("-" * 30)
    print(f"Linux先読み:")
    print(f"  ヒット率: {readahead_results['hit_rate']:.3f}")
    print(f"  プリフェッチ効率: {readahead_results['prefetch_efficiency']:.3f}")
    
    print(f"CluMP強化版:")
    print(f"  ヒット率: {enhanced_results['hit_rate']:.3f}")
    print(f"  プリフェッチ効率: {enhanced_results['prefetch_efficiency']:.3f}")
    print(f"  MC行数: {enhanced_results['memory_usage_mc_rows']}")
    print(f"  予測精度: {enhanced_results['prediction_accuracy']:.3f}")
    print(f"  最終窓サイズ: {enhanced_results['current_prefetch_window']:.1f}")
    
    improvement = enhanced_results['hit_rate'] / readahead_results['hit_rate'] if readahead_results['hit_rate'] > 0 else 0
    print(f"\n改善倍率: {improvement:.2f}x")
    
    return enhanced_results, readahead_results


if __name__ == "__main__":
    random.seed(42)
    enhanced_comparison_test()