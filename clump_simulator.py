#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP (CLUstered Markov-chain Prefetching) Simulator - Paper-Based Implementation
論文準拠完全版実装

基于論文 "CluMP: Clustered Markov Chain for Storage I/O Prefetch" 的精確實現
Section 3.2-3.3の設計仕様とSection 4の評価方法を忠実に再現

主要な修正点:
1. MCRow構造：論文準拠の6フィールド(CN1-CN3, P1-P3)と動的ソート
2. 8ステップアルゴリズム：論文Section 3.3の完全実装
3. チャンク・クラスタ管理：動的割り当てとメモリ効率化
4. Linux先読み比較：論文と同じ条件でのベースライン実装
5. 評価指標：プリフェッチヒット率、ミスプリフェッチ、メモリオーバーヘッド

作成者: GitHub Copilot (論文準拠版)
更新日: 2025年9月19日
参考文献: CluMP論文 Section 3-4
"""

from collections import OrderedDict
import logging
import random
import time
import math
from typing import List, Dict, Tuple, Optional, Any, Union

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class LRUCache:
    """
    LRU (Least Recently Used) キャッシュの実装
    
    CluMPアルゴリズムにおける中核的なキャッシュ管理クラス。
    論文に基づき、プリフェッチ統計も管理する。
    
    統計追跡:
    - prefetch_total: プリフェッチされたブロック総数
    - prefetch_used: 実際にアクセスされたプリフェッチブロック数  
    - prefetch_unused: 未使用のまま追い出されたプリフェッチブロック数
    """
    
    def __init__(self, cache_size_blocks: int):
        """
        LRUキャッシュを初期化
        
        Args:
            cache_size_blocks: キャッシュ容量（ブロック数）
        """
        if cache_size_blocks <= 0:
            raise ValueError("キャッシュサイズは正の値である必要があります")
            
        self.cache_size = cache_size_blocks
        # key=block_id, val=(is_prefetched, was_used_after_prefetch)
        self.cache: OrderedDict[int, Tuple[bool, bool]] = OrderedDict()
        
        # プリフェッチ統計（論文準拠）
        self.prefetch_stats = {
            "prefetch_total": 0,           # プリフェッチ総数
            "prefetch_used": 0,            # 使用されたプリフェッチ数
            "prefetch_unused": 0           # 未使用プリフェッチ数
        }
        
        logging.debug(f"LRUCache初期化: サイズ={cache_size_blocks}ブロック")
    
    def access(self, block_id: int) -> bool:
        """
        ブロックアクセス処理
        
        Args:
            block_id: アクセス対象のブロックID
            
        Returns:
            bool: ヒットした場合True、ミスした場合False
        """
        if block_id in self.cache:
            # キャッシュヒット：LRU順序を更新
            is_prefetched, was_used = self.cache[block_id]
            
            # プリフェッチされたブロックの初回アクセス
            if is_prefetched and not was_used:
                self.prefetch_stats["prefetch_used"] += 1
                was_used = True
            
            # LRU順序更新（最新に移動）
            self.cache[block_id] = (is_prefetched, was_used)
            self.cache.move_to_end(block_id)
            
            return True
        
        return False  # キャッシュミス
    
    def insert(self, block_id: int, is_prefetch: bool = False) -> None:
        """
        ブロックをキャッシュに挿入
        
        Args:
            block_id: 挿入するブロックID
            is_prefetch: プリフェッチによる挿入かどうか
        """
        if block_id in self.cache:
            # 既存ブロックの場合は状態を更新
            _, was_used = self.cache[block_id]
            self.cache[block_id] = (is_prefetch, was_used)
            self.cache.move_to_end(block_id)
            return
        
        # キャッシュ容量チェック
        if len(self.cache) >= self.cache_size:
            # LRU（最も古い）エントリを追い出し
            lru_block, (was_prefetched, was_used) = self.cache.popitem(last=False)
            
            # 未使用プリフェッチの統計更新
            if was_prefetched and not was_used:
                self.prefetch_stats["prefetch_unused"] += 1
        
        # 新ブロック挿入
        self.cache[block_id] = (is_prefetch, False)
        
        # プリフェッチ統計更新
        if is_prefetch:
            self.prefetch_stats["prefetch_total"] += 1
    
    def get_prefetch_stats(self) -> Dict[str, int]:
        """プリフェッチ統計を取得"""
        return self.prefetch_stats.copy()
    
    def get_cache_info(self) -> Dict[str, Any]:
        """キャッシュ情報を取得"""
        return {
            "cache_size": self.cache_size,
            "current_usage": len(self.cache),
            "usage_rate": len(self.cache) / self.cache_size
        }


class MCRow:
    """
    Markov Chain Row - マルコフ連鎖の行（論文準拠版）
    
    論文Section 3.3に基づく正確な実装：
    - CN1, CN2, CN3: 次チャンク候補（確率順）
    - P1, P2, P3: 対応する遷移頻度
    - 動的ソート機能（頻度順、同値なら最新優先）
    - CN3はソート用バッファとしても機能
    """
    
    def __init__(self):
        """MCRowを初期化"""
        # 論文準拠の6フィールド構造
        self.CN1: int = -1  # 最も頻繁にアクセスされるチャンク番号
        self.CN2: int = -1  # 2番目に頻繁にアクセスされるチャンク番号
        self.CN3: int = -1  # 最も最近アクセスされたチャンク番号（ソートバッファ）
        self.P1: int = 0    # CN1への遷移頻度
        self.P2: int = 0    # CN2への遷移頻度  
        self.P3: int = 0    # CN3への遷移頻度
        
        # 最新更新時刻（同値ソート用）
        self._last_update_time = {
            1: 0,  # CN1の最終更新時刻
            2: 0,  # CN2の最終更新時刻
            3: 0   # CN3の最終更新時刻
        }
        self._global_time = 0
    
    def update_transition(self, next_chunk_id: int) -> None:
        """
        遷移を更新（論文準拠アルゴリズム）
        
        Args:
            next_chunk_id: 次にアクセスされたチャンクID
            
        論文の記述：
        "複数のPx値が等しい場合、最も最近更新された値が次にアクセスされる確率が高いと見なされる"
        """
        self._global_time += 1
        
        # 既存チャンクの場合：対応する頻度を増加
        if next_chunk_id == self.CN1:
            self.P1 += 1
            self._last_update_time[1] = self._global_time
        elif next_chunk_id == self.CN2:
            self.P2 += 1
            self._last_update_time[2] = self._global_time
        elif next_chunk_id == self.CN3:
            self.P3 += 1
            self._last_update_time[3] = self._global_time
        else:
            # 新チャンクの場合：CN3を置換
            self.CN3 = next_chunk_id
            self.P3 = 1
            self._last_update_time[3] = self._global_time
        
        # 動的ソート実行（頻度順、同値なら最新優先）
        self._sort_candidates()
    
    def _sort_candidates(self) -> None:
        """
        候補をソート（頻度順、同値なら最新更新優先）
        
        論文の記述：
        "P1とP2が同じ値を持つが、最も最近更新されたCN2に格納されたチャンク値が
        CN1のチャンク値と交換され、CN1の以前の値がCN2に割り当てられる"
        """
        # 現在の候補リスト（有効なもののみ）
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
        
        # ソート結果を反映
        for i, (chunk_id, freq, update_time, original_pos) in enumerate(candidates):
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
        """
        次のチャンクを予測
        
        Returns:
            Optional[int]: CN1（最高確率の次チャンク）、存在しない場合None
            
        論文の記述：
        "プリフェッチ目的では、CluMPは常にCN1を参照し、それを使用して次のI/O要求を予測する"
        """
        return self.CN1 if self.CN1 >= 0 else None
    
    def get_transition_info(self) -> Dict[str, Any]:
        """遷移情報を取得"""
        return {
            "CN1": self.CN1, "P1": self.P1,
            "CN2": self.CN2, "P2": self.P2,
            "CN3": self.CN3, "P3": self.P3,
            "total_transitions": self.P1 + self.P2 + self.P3,
            "prediction": self.predict_next_chunk()
        }


class ClusterManager:
    """
    クラスタマネージャ（論文準拠版）
    
    論文Section 3.2の設計：
    - チャンク = ディスクブロックのセット
    - クラスタ = MCフラグメントのセット
    - 動的割り当て（必要時のみメモリ使用）
    - メモリ使用量 = CL_total × 24B × CL_size
    """
    
    def __init__(self, cluster_size_chunks: int):
        """
        クラスタマネージャを初期化
        
        Args:
            cluster_size_chunks: クラスタサイズ（チャンク数）
        """
        if cluster_size_chunks <= 0:
            raise ValueError("クラスタサイズは正の値である必要があります")
            
        self.cluster_size = cluster_size_chunks
        
        # 動的MC割り当て管理
        # key=cluster_id, value=Dict[chunk_id_in_cluster, MCRow]
        self.clusters: Dict[int, Dict[int, MCRow]] = {}
        
        # メモリ使用量追跡
        self.allocated_mc_rows = 0
        
        logging.debug(f"ClusterManager初期化: CL_size={cluster_size_chunks}")
    
    def get_mc_row(self, chunk_id: int, allocate: bool = False) -> Optional[MCRow]:
        """
        MCRowを取得（必要に応じて動的割り当て）
        
        Args:
            chunk_id: チャンクID
            allocate: 存在しない場合に新規割り当てするか
            
        Returns:
            Optional[MCRow]: MCRow、存在しない場合None
        """
        cluster_id = chunk_id // self.cluster_size
        chunk_in_cluster = chunk_id % self.cluster_size
        
        # クラスタが存在しない場合
        if cluster_id not in self.clusters:
            if not allocate:
                return None
            # 新クラスタを動的割り当て
            self.clusters[cluster_id] = {}
            logging.debug(f"新クラスタ割り当て: cluster_id={cluster_id}")
        
        # MCRowが存在しない場合
        if chunk_in_cluster not in self.clusters[cluster_id]:
            if not allocate:
                return None
            # 新MCRowを動的割り当て
            self.clusters[cluster_id][chunk_in_cluster] = MCRow()
            self.allocated_mc_rows += 1
            logging.debug(f"新MCRow割り当て: chunk_id={chunk_id}, "
                         f"total_mc_rows={self.allocated_mc_rows}")
        
        return self.clusters[cluster_id][chunk_in_cluster]
    
    def get_memory_usage(self) -> int:
        """
        MCのメモリ使用量を取得（論文の計算式に基づく）
        
        Returns:
            int: メモリ使用量（バイト）
            
        論文の計算式：
        Mem_required = CL_total × 24B × CL_size
        ただし実際の使用量は動的割り当てにより大幅に削減
        """
        # 24B = 6フィールド × 4B (CN1-CN3, P1-P3)
        bytes_per_mc_row = 24
        return self.allocated_mc_rows * bytes_per_mc_row
    
    def get_cluster_info(self) -> Dict[str, Any]:
        """クラスタ情報を取得"""
        total_possible_clusters = len(self.clusters) * self.cluster_size if self.clusters else 0
        
        return {
            "cluster_size": self.cluster_size,
            "allocated_clusters": len(self.clusters),
            "allocated_mc_rows": self.allocated_mc_rows,
            "memory_usage_bytes": self.get_memory_usage(),
            "memory_usage_kb": self.get_memory_usage() / 1024,
            "efficiency": (self.allocated_mc_rows / max(total_possible_clusters, 1)) if total_possible_clusters > 0 else 0
        }


class CluMPSimulator:
    """
    CluMP アルゴリズムのメインシミュレータ（論文準拠版）
    
    論文Section 3.3の8ステップアルゴリズムを完全実装：
    1. ディスクI/O読み取り操作が要求される
    2. 要求されたディスクブロックがメモリに存在するかチェック
    3. 要求されたデータがメモリに存在しない場合、ディスクからの読み取りを要求
    4. ディスクから対応するデータを取得し、メモリに読み込む
    5. データに対する既存のマルコフ連鎖があるかチェック
    6. 予測されたマルコフ連鎖が存在する場合、対応するチャンク番号の情報を更新
    7. 更新されたマルコフ連鎖の予測を使用してプリフェッチを実行
    8. マルコフ連鎖が存在しない場合、利用可能な情報を使用して新しいものを作成
    """
    
    def __init__(self, chunk_size_blocks: int, cluster_size_chunks: int, 
                 cache_size_blocks: int, prefetch_window_blocks: int):
        """
        CluMPシミュレータを初期化
        
        Args:
            chunk_size_blocks: チャンクサイズ（ブロック数）
            cluster_size_chunks: クラスタサイズ（チャンク数）
            cache_size_blocks: キャッシュサイズ（ブロック数）
            prefetch_window_blocks: プリフェッチ窓サイズ（ブロック数）
        """
        # パラメータ検証
        if any(x <= 0 for x in [chunk_size_blocks, cluster_size_chunks, 
                                cache_size_blocks, prefetch_window_blocks]):
            raise ValueError("すべてのパラメータは正の値である必要があります")
        
        # 基本パラメータ
        self.chunk_size = chunk_size_blocks
        self.cluster_size = cluster_size_chunks
        self.cache_size = cache_size_blocks
        self.prefetch_window = prefetch_window_blocks
        
        # コンポーネント初期化
        self.cache = LRUCache(cache_size_blocks)
        self.cluster_manager = ClusterManager(cluster_size_chunks)
        
        # 統計カウンタ
        self.total_accesses = 0
        self.cache_hits = 0
        self.previous_chunk_id: Optional[int] = None
        
        logging.info(f"CluMPシミュレータ初期化: chunk={chunk_size_blocks}, "
                    f"cluster={cluster_size_chunks}, cache={cache_size_blocks}, "
                    f"prefetch_window={prefetch_window_blocks}")
    
    def _get_chunk_id(self, block_id: int) -> int:
        """ブロックIDからチャンクIDを計算"""
        return block_id // self.chunk_size
    
    def _prefetch_chunk(self, chunk_id: int) -> None:
        """
        チャンクをプリフェッチ（論文準拠）
        
        Args:
            chunk_id: プリフェッチ対象のチャンクID
        """
        start_block = chunk_id * self.chunk_size
        
        # プリフェッチ窓サイズ分のブロックをプリフェッチ
        for i in range(self.prefetch_window):
            prefetch_block = start_block + i
            if not self.cache.access(prefetch_block):
                # キャッシュミスの場合、プリフェッチとして挿入
                self.cache.insert(prefetch_block, is_prefetch=True)
                logging.debug(f"プリフェッチ: block={prefetch_block}")
    
    def process_access(self, block_id: int) -> bool:
        """
        ブロックアクセス処理（論文Section 3.3の8ステップ）
        
        Args:
            block_id: アクセスするブロックID
            
        Returns:
            bool: キャッシュヒットした場合True
        """
        self.total_accesses += 1
        current_chunk_id = self._get_chunk_id(block_id)
        
        # Step 1: ディスクI/O読み取り操作が要求される
        logging.debug(f"Step 1: I/O要求 block={block_id}, chunk={current_chunk_id}")
        
        # Step 2: 要求されたディスクブロックがメモリに存在するかチェック
        cache_hit = self.cache.access(block_id)
        logging.debug(f"Step 2: メモリ存在確認 hit={cache_hit}")
        
        if cache_hit:
            self.cache_hits += 1
            # ヒットの場合もMC更新は実行
            if self.previous_chunk_id is not None:
                self._update_markov_chain(current_chunk_id)
        else:
            # Step 3: ディスクからの読み取りを要求
            # Step 4: データ取得・メモリ読み込み
            logging.debug(f"Step 3-4: ディスク読み取り・メモリ読み込み")
            self.cache.insert(block_id, is_prefetch=False)
            
            # Step 5: 既存のマルコフ連鎖があるかチェック
            # Step 6: MC情報更新
            if self.previous_chunk_id is not None:
                self._update_markov_chain(current_chunk_id)
            
            # Step 7: CN1ベースプリフェッチ実行
            self._execute_prediction_and_prefetch(current_chunk_id)
            
            # Step 8: 新MCの作成（update_markov_chainで自動処理）
        
        # 次回のために現在チャンクを保存
        self.previous_chunk_id = current_chunk_id
        return cache_hit
    
    def _update_markov_chain(self, current_chunk_id: int) -> None:
        """
        マルコフ連鎖を更新（Step 6-8）
        
        Args:
            current_chunk_id: 現在のチャンクID
        """
        if self.previous_chunk_id is None:
            return
        
        # 前チャンクのMCRowを取得（必要に応じて新規作成）
        mc_row = self.cluster_manager.get_mc_row(self.previous_chunk_id, allocate=True)
        
        # 遷移を更新
        mc_row.update_transition(current_chunk_id)
        
        logging.debug(f"MC更新: {self.previous_chunk_id} -> {current_chunk_id}")
    
    def _execute_prediction_and_prefetch(self, current_chunk_id: int) -> None:
        """
        予測とプリフェッチを実行（Step 7）
        
        Args:
            current_chunk_id: 現在のチャンクID
        """
        # 現在チャンクのMCRowから予測
        mc_row = self.cluster_manager.get_mc_row(current_chunk_id, allocate=False)
        
        if mc_row is not None:
            predicted_chunk = mc_row.predict_next_chunk()
            if predicted_chunk is not None:
                logging.debug(f"予測プリフェッチ: chunk={predicted_chunk}")
                self._prefetch_chunk(predicted_chunk)
    
    def get_evaluation_metrics(self) -> Dict[str, Any]:
        """
        評価指標を取得（論文Section 4準拠）
        
        Returns:
            Dict[str, Any]: 評価指標辞書
        """
        prefetch_stats = self.cache.get_prefetch_stats()
        cluster_info = self.cluster_manager.get_cluster_info()
        cache_info = self.cache.get_cache_info()
        
        # プリフェッチ効率計算
        prefetch_efficiency = 0.0
        if prefetch_stats["prefetch_total"] > 0:
            prefetch_efficiency = prefetch_stats["prefetch_used"] / prefetch_stats["prefetch_total"]
        
        # ヒット率計算
        hit_rate = 0.0
        if self.total_accesses > 0:
            hit_rate = self.cache_hits / self.total_accesses
        
        return {
            # 基本統計
            "total_accesses": self.total_accesses,
            "cache_hits": self.cache_hits,
            "hit_rate": hit_rate,
            
            # プリフェッチ統計（論文Section 4.3準拠）
            "prefetch_total": prefetch_stats["prefetch_total"],
            "prefetch_used": prefetch_stats["prefetch_used"],
            "prefetch_unused": prefetch_stats["prefetch_unused"],
            "prefetch_efficiency": prefetch_efficiency,
            
            # メモリオーバーヘッド（論文Section 4.4準拠）
            "memory_usage_mc_rows": cluster_info["allocated_mc_rows"],
            "memory_usage_bytes": cluster_info["memory_usage_bytes"],
            "memory_usage_kb": cluster_info["memory_usage_kb"],
            
            # パラメータ設定
            "chunk_size": self.chunk_size,
            "cluster_size": self.cluster_size,
            "cache_size": self.cache_size,
            "prefetch_window": self.prefetch_window,
            
            # 詳細情報
            "cache_info": cache_info,
            "cluster_info": cluster_info
        }


class LinuxReadAhead:
    """
    Linux先読みアルゴリズム（論文準拠版）
    
    論文Section 2.1とSection 4の比較条件に基づく実装：
    - 逐次アクセス検出
    - 128KB初期窓サイズ
    - 継続的逐次アクセス時の窓倍増
    - 非逐次アクセス時の窓リセット
    """
    
    def __init__(self, cache_size_blocks: int, initial_window_kb: int = 128):
        """
        Linux先読みを初期化
        
        Args:
            cache_size_blocks: キャッシュサイズ（ブロック数）
            initial_window_kb: 初期先読み窓サイズ（KB）
        """
        self.cache = LRUCache(cache_size_blocks)
        self.cache_size = cache_size_blocks
        
        # 先読みパラメータ（論文準拠）
        self.initial_window_kb = initial_window_kb
        self.current_window_kb = initial_window_kb
        self.max_window_kb = 2048  # 最大窓サイズ
        
        # 逐次アクセス検出
        self.last_block_id: Optional[int] = None
        self.consecutive_sequential = 0
        self.sequential_threshold = 2  # 逐次判定閾値
        
        # 統計
        self.total_accesses = 0
        self.cache_hits = 0
        
        # 4KBブロックサイズ仮定
        self.block_size_kb = 4
        
        logging.info(f"Linux先読み初期化: cache={cache_size_blocks}, "
                    f"window={initial_window_kb}KB")
    
    def _is_sequential(self, block_id: int) -> bool:
        """逐次アクセスかどうか判定"""
        if self.last_block_id is None:
            return False
        return block_id == self.last_block_id + 1
    
    def _execute_readahead(self, block_id: int) -> None:
        """
        先読み実行（論文準拠アルゴリズム）
        
        Args:
            block_id: 開始ブロックID
        """
        # 窓サイズ（ブロック数）計算
        window_blocks = self.current_window_kb // self.block_size_kb
        
        # 先読み実行
        for i in range(1, window_blocks + 1):
            readahead_block = block_id + i
            if not self.cache.access(readahead_block):
                self.cache.insert(readahead_block, is_prefetch=True)
                logging.debug(f"先読み: block={readahead_block}")
    
    def process_access(self, block_id: int) -> bool:
        """
        ブロックアクセス処理（Linux先読みアルゴリズム）
        
        Args:
            block_id: アクセスするブロックID
            
        Returns:
            bool: キャッシュヒットした場合True
        """
        self.total_accesses += 1
        
        # キャッシュアクセス
        cache_hit = self.cache.access(block_id)
        if cache_hit:
            self.cache_hits += 1
        else:
            # キャッシュミス：ブロックを読み込み
            self.cache.insert(block_id, is_prefetch=False)
        
        # 逐次性チェック
        is_sequential = self._is_sequential(block_id)
        
        if is_sequential:
            self.consecutive_sequential += 1
            
            # 継続的逐次アクセス：窓倍増
            if self.consecutive_sequential >= self.sequential_threshold:
                self.current_window_kb = min(self.current_window_kb * 2, 
                                           self.max_window_kb)
                logging.debug(f"窓倍増: {self.current_window_kb}KB")
            
            # 先読み実行
            self._execute_readahead(block_id)
            
        else:
            # 非逐次アクセス：窓リセット
            self.consecutive_sequential = 0
            self.current_window_kb = self.initial_window_kb
            # 先読みは実行しない
        
        self.last_block_id = block_id
        return cache_hit
    
    def get_evaluation_metrics(self) -> Dict[str, Any]:
        """評価指標を取得"""
        prefetch_stats = self.cache.get_prefetch_stats()
        
        # プリフェッチ効率計算
        prefetch_efficiency = 0.0
        if prefetch_stats["prefetch_total"] > 0:
            prefetch_efficiency = prefetch_stats["prefetch_used"] / prefetch_stats["prefetch_total"]
        
        # ヒット率計算
        hit_rate = 0.0
        if self.total_accesses > 0:
            hit_rate = self.cache_hits / self.total_accesses
        
        return {
            # 基本統計
            "total_accesses": self.total_accesses,
            "cache_hits": self.cache_hits,
            "hit_rate": hit_rate,
            
            # プリフェッチ統計
            "prefetch_total": prefetch_stats["prefetch_total"],
            "prefetch_used": prefetch_stats["prefetch_used"],
            "prefetch_unused": prefetch_stats["prefetch_unused"],
            "prefetch_efficiency": prefetch_efficiency,
            
            # 先読み固有情報
            "current_window_kb": self.current_window_kb,
            "consecutive_sequential": self.consecutive_sequential,
            "algorithm": "Linux ReadAhead"
        }


class WorkloadGenerator:
    """
    ワークロード生成器（論文Section 4.1準拠）
    
    KVM起動とLinuxカーネルビルドに相当する合成ワークロードを生成
    """
    
    @staticmethod
    def generate_kvm_workload(total_blocks: int = 10000, 
                             block_range: int = 50000) -> List[int]:
        """
        KVM起動ワークロード生成（42.53MB相当）
        
        Args:
            total_blocks: 総アクセス数
            block_range: ブロック範囲
            
        Returns:
            List[int]: ブロックアクセスシーケンス
        """
        trace = []
        
        # KVM起動パターン：
        # 40% 逐次アクセス（起動シーケンス）
        # 35% ランダムアクセス（設定ファイル）
        # 25% 小規模ジャンプ（ライブラリロード）
        
        current_block = random.randint(0, block_range // 10)
        
        for _ in range(total_blocks):
            access_type = random.random()
            
            if access_type < 0.4:
                # 逐次アクセス
                trace.append(current_block)
                current_block += 1
            elif access_type < 0.75:
                # ランダムアクセス
                current_block = random.randint(0, block_range)
                trace.append(current_block)
            else:
                # 小規模ジャンプ
                jump = random.randint(10, 100)
                current_block += jump
                trace.append(current_block % block_range)
        
        return trace
    
    @staticmethod
    def generate_kernel_build_workload(total_blocks: int = 50000,
                                     block_range: int = 200000) -> List[int]:
        """
        Linuxカーネルビルドワークロード生成（7.96GB相当）
        
        Args:
            total_blocks: 総アクセス数
            block_range: ブロック範囲
            
        Returns:
            List[int]: ブロックアクセスシーケンス
        """
        trace = []
        
        # カーネルビルドパターン：
        # 30% 逐次アクセス（ソースファイル読み込み）
        # 50% ランダムアクセス（ヘッダーファイル）
        # 20% 大規模ジャンプ（並列コンパイル）
        
        current_block = random.randint(0, block_range // 10)
        
        for _ in range(total_blocks):
            access_type = random.random()
            
            if access_type < 0.3:
                # 逐次アクセス（ソースファイル）
                trace.append(current_block)
                current_block += 1
            elif access_type < 0.8:
                # ランダムアクセス（ヘッダーファイル）
                current_block = random.randint(0, block_range)
                trace.append(current_block)
            else:
                # 大規模ジャンプ（並列コンパイル）
                jump = random.randint(1000, 10000)
                current_block += jump
                trace.append(current_block % block_range)
        
        return trace


def compare_clump_vs_readahead(trace: List[int],
                              clump_params: Dict[str, int],
                              cache_size: int = 4096) -> Dict[str, Any]:
    """
    CluMPとLinux先読みの比較実験（論文準拠）
    
    Args:
        trace: アクセストレース
        clump_params: CluMPパラメータ
        cache_size: キャッシュサイズ
        
    Returns:
        Dict[str, Any]: 比較結果
    """
    # CluMP実行
    clump = CluMPSimulator(
        chunk_size_blocks=clump_params["chunk_size"],
        cluster_size_chunks=clump_params["cluster_size"],
        cache_size_blocks=cache_size,
        prefetch_window_blocks=clump_params["prefetch_window"]
    )
    
    for block_id in trace:
        clump.process_access(block_id)
    
    clump_results = clump.get_evaluation_metrics()
    
    # Linux先読み実行
    readahead = LinuxReadAhead(cache_size_blocks=cache_size)
    
    for block_id in trace:
        readahead.process_access(block_id)
    
    readahead_results = readahead.get_evaluation_metrics()
    
    # 比較結果
    improvement = {
        "hit_rate_improvement": clump_results["hit_rate"] / readahead_results["hit_rate"] if readahead_results["hit_rate"] > 0 else float('inf'),
        "hit_rate_difference": clump_results["hit_rate"] - readahead_results["hit_rate"],
        "prefetch_efficiency_improvement": clump_results["prefetch_efficiency"] / readahead_results["prefetch_efficiency"] if readahead_results["prefetch_efficiency"] > 0 else float('inf')
    }
    
    return {
        "clump": clump_results,
        "readahead": readahead_results,
        "improvement": improvement
    }


if __name__ == "__main__":
    # 乱数シード固定（再現性確保）
    random.seed(42)
    
    print("CluMP論文準拠シミュレータ")
    print("=" * 60)
    
    # 論文準拠パラメータ
    clump_params = {
        "chunk_size": 16,      # 論文で効果的とされた値
        "cluster_size": 64,    # 論文で効果的とされた値
        "prefetch_window": 16
    }
    
    # KVMワークロードテスト
    print("\n🚀 KVMワークロードテスト")
    print("-" * 40)
    
    kvm_trace = WorkloadGenerator.generate_kvm_workload(total_blocks=10000)
    kvm_results = compare_clump_vs_readahead(kvm_trace, clump_params)
    
    print(f"Linux先読み ヒット率: {kvm_results['readahead']['hit_rate']:.3f}")
    print(f"CluMP ヒット率: {kvm_results['clump']['hit_rate']:.3f}")
    print(f"改善倍率: {kvm_results['improvement']['hit_rate_improvement']:.2f}x")
    print(f"CluMP MC行数: {kvm_results['clump']['memory_usage_mc_rows']}")
    
    # カーネルビルドワークロードテスト
    print("\n🔨 カーネルビルドワークロードテスト")
    print("-" * 40)
    
    kernel_trace = WorkloadGenerator.generate_kernel_build_workload(total_blocks=20000)
    kernel_results = compare_clump_vs_readahead(kernel_trace, clump_params)
    
    print(f"Linux先読み ヒット率: {kernel_results['readahead']['hit_rate']:.3f}")
    print(f"CluMP ヒット率: {kernel_results['clump']['hit_rate']:.3f}")
    print(f"改善倍率: {kernel_results['improvement']['hit_rate_improvement']:.2f}x")
    print(f"CluMP MC行数: {kernel_results['clump']['memory_usage_mc_rows']}")
    
    print("\n✅ 論文準拠シミュレーション完了")
    print("目標値: KVM 1.91x改善, カーネルビルド 1.31x改善")