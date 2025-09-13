#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP (CLUstered Markov-chain Prefetching) Simulator
要件定義書に基づく抜本的改良版

目的:
- CluMPアルゴリズムをシミュレーションにより再現
- Linux read-aheadや単純なプリフェッチ方式と比較可能
- 論文の性能評価指標（ヒット率、無駄プリフェッチ率、メモリ消費量など）を再現

アーキテクチャ:
1. LRUCache: キャッシュ管理とプリフェッチ統計追跡
2. MCRow: マルコフ連鎖の状態遷移記録（CN1-CN3, P1-P3）
3. ClusterManager: MCRowのオンデマンド割り当て管理
4. CluMPSimulator: メインアルゴリズムの実装
5. TraceGenerator: 合成ワークロード生成

作成者: GitHub Copilot & User
更新日: 2025年9月13日
"""

from collections import OrderedDict
import random
import time
import statistics
import logging
from typing import List, Dict, Tuple, Optional, Any, Union

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class LRUCache:
    """
    LRU (Least Recently Used) キャッシュの実装
    
    CluMPアルゴリズムにおける中核的なキャッシュ管理クラス。
    要件定義書に基づき、プリフェッチ統計も管理する。
    
    機能:
    - ブロックレベルのキャッシュ管理
    - LRU (Least Recently Used) エビクション方式
    - プリフェッチブロックの統計追跡
    - ヒット/ミス率の正確な計算
    
    統計追跡:
    - prefetch_total: プリフェッチされたブロック総数
    - prefetch_used: 実際にアクセスされたプリフェッチブロック数
    - prefetch_unused_evicted: 未使用のまま追い出されたプリフェッチブロック数
    """
    
    def __init__(self, cache_size_blocks: int):
        """
        LRUキャッシュを初期化
        
        Args:
            cache_size_blocks: キャッシュ容量（ブロック数）
            
        Raises:
            ValueError: キャッシュサイズが無効な場合
        """
        if cache_size_blocks <= 0:
            raise ValueError(f"キャッシュサイズは正の値である必要があります: {cache_size_blocks}")
            
        self.cache_size = cache_size_blocks
        # key=block_id, val=(is_prefetched, was_used_after_prefetch)
        # OrderedDictを使用してLRU順序を効率的に管理
        self.cache: OrderedDict[int, Tuple[bool, bool]] = OrderedDict()
        
        # プリフェッチ統計（要件定義書準拠）
        self.prefetch_stats = {
            "prefetch_total": 0,           # プリフェッチされたブロック数
            "prefetch_used": 0,            # 実際アクセスされヒットに貢献したプリフェッチ数
            "prefetch_unused_evicted": 0   # 使われずキャッシュから追い出されたプリフェッチ数
        }
        
        logging.debug(f"LRUCache初期化: サイズ={cache_size_blocks}ブロック")
    
    def access(self, block_id: int) -> bool:
        """
        ブロックアクセス処理
        
        指定されたブロックがキャッシュに存在するかチェックし、
        存在する場合はLRU順序を更新してヒットを返す。
        
        Args:
            block_id: アクセス対象のブロックID
            
        Returns:
            bool: ヒットした場合True、ミスした場合False
            
        Note:
            プリフェッチされたブロックが初回アクセスされた場合、
            prefetch_used統計を更新する。
        """
        if block_id in self.cache:
            # キャッシュヒット: LRU順序を更新（最新にする）
            is_prefetched, was_used = self.cache.pop(block_id)
            
            # プリフェッチされたブロックが初めて使用される場合
            if is_prefetched and not was_used:
                self.prefetch_stats["prefetch_used"] += 1
                was_used = True
                logging.debug(f"プリフェッチブロック {block_id} が初回使用されました")
            
            # 最新位置に再挿入（LRU更新）
            self.cache[block_id] = (is_prefetched, was_used)
            return True
        
        return False  # キャッシュミス
    
    def insert(self, block_id: int, is_prefetch: bool = False) -> None:
        """
        ブロックをキャッシュに挿入
        
        新しいブロックをキャッシュに追加する。キャッシュが満杯の場合は
        LRU（最も古い）エントリを追い出してスペースを確保する。
        
        Args:
            block_id: 挿入するブロックID
            is_prefetch: プリフェッチによる挿入かどうか
            
        Note:
            - 既存ブロックの場合は状態を更新
            - キャッシュ満杯時はLRUエントリを追い出し
            - 未使用プリフェッチの追い出し時は統計を更新
        """
        if block_id in self.cache:
            # 既にキャッシュに存在する場合は状態を更新
            existing_prefetch, was_used = self.cache.pop(block_id)
            is_prefetched = existing_prefetch or is_prefetch
            self.cache[block_id] = (is_prefetched, was_used)
            logging.debug(f"既存ブロック {block_id} の状態を更新")
            return
        
        # キャッシュ容量チェック
        if len(self.cache) >= self.cache_size:
            # LRU（最も古い）エントリを追い出し
            evicted_block, (evicted_prefetch, evicted_used) = self.cache.popitem(last=False)
            
            # 未使用プリフェッチの追い出しを記録
            if evicted_prefetch and not evicted_used:
                self.prefetch_stats["prefetch_unused_evicted"] += 1
                logging.debug(f"未使用プリフェッチブロック {evicted_block} を追い出し")
        
        # 新しいブロックを挿入
        self.cache[block_id] = (is_prefetch, False)
        
        # プリフェッチ統計を更新
        if is_prefetch:
            self.prefetch_stats["prefetch_total"] += 1
            logging.debug(f"プリフェッチブロック {block_id} を挿入")
    
    def get_prefetch_stats(self) -> Dict[str, int]:
        """
        プリフェッチ統計を取得
        
        Returns:
            Dict[str, int]: プリフェッチ関連の統計情報
        """
        return dict(self.prefetch_stats)
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        キャッシュの詳細情報を取得（デバッグ用）
        
        Returns:
            Dict[str, Any]: キャッシュの詳細情報
        """
        total_blocks = len(self.cache)
        prefetch_blocks = sum(1 for is_prefetch, _ in self.cache.values() if is_prefetch)
        
        return {
            "total_blocks": total_blocks,
            "prefetch_blocks": prefetch_blocks,
            "regular_blocks": total_blocks - prefetch_blocks,
            "utilization": total_blocks / self.cache_size if self.cache_size > 0 else 0
        }


class MCRow:
    """
    Markov Chain Row - マルコフ連鎖の行
    
    CluMPアルゴリズムの核心部分。各チャンクから他のチャンクへの
    状態遷移確率を学習・記録し、次のアクセス先を予測する。
    
    データ構造:
    - CN1, CN2, CN3: 遷移候補チャンクID（確率順）
    - P1, P2, P3: 対応する遷移頻度
    
    学習方式:
    - オンライン学習: アクセス毎に遷移を記録
    - 頻度ベース: 遷移回数により確率を計算
    - 上位3候補のみ保持（メモリ効率化）
    
    予測方式:
    - CN1（最頻出遷移先）を次のアクセス予測として使用
    """
    
    # クラス定数: 保持する候補数
    MAX_CANDIDATES = 3
    
    def __init__(self):
        """
        MCRowを初期化
        
        すべての候補チャンクIDと確率を初期状態に設定する。
        """
        # 候補チャンクID（CN1, CN2, CN3）
        self.candidate_chunks: List[Optional[int]] = [None] * self.MAX_CANDIDATES
        # 出現頻度（P1, P2, P3）
        self.probabilities: List[int] = [0] * self.MAX_CANDIDATES
        
        logging.debug("MCRow初期化完了")
    
    def update_transition(self, next_chunk_id: int) -> None:
        """
        状態遷移を更新
        
        新しい遷移「現在のチャンク → next_chunk_id」を記録し、
        候補リストを頻度順に並び替える。
        
        Args:
            next_chunk_id: 遷移先のチャンクID
            
        Algorithm:
        1. 既存候補の場合: 頻度を増加してソート
        2. 新規候補の場合: CN3位置に挿入してソート
        3. バブルソートで頻度順に並び替え
        """
        if next_chunk_id in self.candidate_chunks:
            # 既存の候補の場合、頻度を増加してソート
            index = self.candidate_chunks.index(next_chunk_id)
            self.probabilities[index] += 1
            
            # 頻度順にバブルソート（降順）
            self._bubble_sort_candidates(index)
            
            logging.debug(f"既存候補 {next_chunk_id} の頻度を更新: {self.probabilities[0]}")
        else:
            # 新しい候補の場合、CN3位置に挿入
            self.candidate_chunks[2] = next_chunk_id
            self.probabilities[2] = 1
            
            # 必要に応じてバブルアップ
            self._bubble_sort_candidates(2)
            
            logging.debug(f"新規候補 {next_chunk_id} を追加")
    
    def _bubble_sort_candidates(self, start_index: int) -> None:
        """
        候補リストを頻度順にバブルソート
        
        Args:
            start_index: ソート開始位置
            
        Note:
            効率のため、変更された位置からのみソートを実行
        """
        i = start_index
        while i > 0 and (self.probabilities[i] > self.probabilities[i-1] or 
                         (self.probabilities[i] == self.probabilities[i-1] and 
                          self.candidate_chunks[i] is not None)):
            # スワップ実行
            self.probabilities[i], self.probabilities[i-1] = \
                self.probabilities[i-1], self.probabilities[i]
            self.candidate_chunks[i], self.candidate_chunks[i-1] = \
                self.candidate_chunks[i-1], self.candidate_chunks[i]
            i -= 1
    
    def predict_next_chunk(self) -> Optional[int]:
        """
        次のチャンクを予測
        
        最も頻度の高い遷移先（CN1）を予測結果として返す。
        
        Returns:
            Optional[int]: 予測されるチャンクID（CN1）、なければNone
        """
        prediction = self.candidate_chunks[0]
        if prediction is not None:
            logging.debug(f"チャンク予測: {prediction} (頻度: {self.probabilities[0]})")
        return prediction
    
    def get_transition_info(self) -> Dict[str, Any]:
        """
        遷移情報の詳細を取得（デバッグ・分析用）
        
        Returns:
            Dict[str, Any]: 遷移候補と確率の詳細情報
        """
        total_transitions = sum(self.probabilities)
        
        candidates_info = []
        for i in range(self.MAX_CANDIDATES):
            if self.candidate_chunks[i] is not None:
                probability = self.probabilities[i] / total_transitions if total_transitions > 0 else 0
                candidates_info.append({
                    "rank": i + 1,
                    "chunk_id": self.candidate_chunks[i],
                    "frequency": self.probabilities[i],
                    "probability": probability
                })
        
        return {
            "total_transitions": total_transitions,
            "candidates": candidates_info
        }


class ClusterManager:
    """
    クラスタマネージャ
    
    メモリ効率化のため、複数のチャンクをCLsize単位にまとめ、
    MCRowをオンデマンドで割り当て管理する。
    
    設計思想:
    - オンデマンド割り当て: 使用されないMCRowはメモリを消費しない
    - 階層管理: クラスタ → チャンク → MCRowの階層構造
    - 効率的検索: クラスタIDによる高速アクセス
    
    メモリ最適化:
    - 未使用チャンクのMCRowは作成しない
    - アクセスが発生した時点で初めて割り当て
    - 全体のメモリ使用量を追跡
    """
    
    def __init__(self, cluster_size_chunks: int):
        """
        クラスタマネージャを初期化
        
        Args:
            cluster_size_chunks: クラスタサイズ（チャンク数）
            
        Raises:
            ValueError: クラスタサイズが無効な場合
        """
        if cluster_size_chunks <= 0:
            raise ValueError(f"クラスタサイズは正の値である必要があります: {cluster_size_chunks}")
            
        self.cluster_size = cluster_size_chunks
        # cluster_id -> {chunk_id: MCRow}
        self.clusters: Dict[int, Dict[int, MCRow]] = {}
        
        logging.debug(f"ClusterManager初期化: クラスタサイズ={cluster_size_chunks}チャンク")
    
    def get_mc_row(self, chunk_id: int, allocate: bool = False) -> Optional[MCRow]:
        """
        指定されたチャンクのMCRowを取得
        
        チャンクIDから対応するクラスタを特定し、MCRowを取得する。
        allocateがTrueの場合、存在しない場合は新規作成する。
        
        Args:
            chunk_id: チャンクID
            allocate: 存在しない場合に新規作成するかどうか
            
        Returns:
            Optional[MCRow]: MCRowオブジェクト、存在しなければNone
            
        Note:
            オンデマンド割り当てにより、メモリ使用量を最小化
        """
        cluster_id = chunk_id // self.cluster_size
        
        # クラスタの取得または作成
        if cluster_id in self.clusters:
            cluster = self.clusters[cluster_id]
        else:
            if not allocate:
                return None
            cluster = {}
            self.clusters[cluster_id] = cluster
            logging.debug(f"新規クラスタ {cluster_id} を作成")
        
        # MCRowの取得または作成
        mc_row = cluster.get(chunk_id)
        if mc_row is None and allocate:
            mc_row = MCRow()
            cluster[chunk_id] = mc_row
            logging.debug(f"チャンク {chunk_id} のMCRowを新規作成 (クラスタ {cluster_id})")
        
        return mc_row
    
    def get_memory_usage(self) -> int:
        """
        メモリ使用量（生成されたMCRow数）を取得
        
        Returns:
            int: MCRow数
        """
        total_rows = 0
        for cluster in self.clusters.values():
            total_rows += len(cluster)
        return total_rows
    
    def get_cluster_info(self) -> Dict[str, Any]:
        """
        クラスタの詳細情報を取得（分析・デバッグ用）
        
        Returns:
            Dict[str, Any]: クラスタとMCRowの統計情報
        """
        total_clusters = len(self.clusters)
        total_mc_rows = self.get_memory_usage()
        
        cluster_utilization = []
        for cluster_id, cluster in self.clusters.items():
            cluster_utilization.append({
                "cluster_id": cluster_id,
                "mc_rows": len(cluster),
                "utilization": len(cluster) / self.cluster_size
            })
        
        avg_utilization = (total_mc_rows / (total_clusters * self.cluster_size) 
                          if total_clusters > 0 else 0)
        
        return {
            "total_clusters": total_clusters,
            "total_mc_rows": total_mc_rows,
            "cluster_size": self.cluster_size,
            "average_utilization": avg_utilization,
            "cluster_details": cluster_utilization
        }


class CluMPSimulator:
    """
    CluMP アルゴリズムのメインシミュレータ
    
    要件定義書のアルゴリズム処理フローに従って実装された、
    CluMP（CLUstered Markov-chain Prefetching）の中核実装。
    
    アルゴリズム概要:
    1. 複数のブロックを「チャンク」単位にまとめる
    2. マルコフ連鎖で「チャンクA → チャンクB」の遷移を学習
    3. 学習した遷移確率で次のアクセス先を予測
    4. 予測したチャンクを事前にプリフェッチして性能向上
    
    処理フロー（要件定義書準拠）:
    1. アクセス処理：キャッシュを確認し、ヒット/ミスを判定
    2. キャッシュ更新：ミスならブロックを読み込み、LRU方式で管理
    3. MC更新：「前チャンク → 現チャンク」の遷移を更新
    4. 予測・プリフェッチ：CN1を参照し、予測チャンクをPrefetchWindow分ロード
    
    特徴:
    - オンライン学習：アクセス毎にパターンを更新
    - メモリ効率：未使用チャンクのMCRowは作成しない
    - 統計追跡：詳細なプリフェッチ効果を測定
    """
    
    def __init__(self, chunk_size_blocks: int, cluster_size_chunks: int, 
                 cache_size_blocks: int, prefetch_window_blocks: int):
        """
        CluMPシミュレータを初期化
        
        Args:
            chunk_size_blocks: チャンクサイズ（ブロック数）
            cluster_size_chunks: クラスタサイズ（チャンク数）
            cache_size_blocks: キャッシュ容量（ブロック数）
            prefetch_window_blocks: プリフェッチ時に読み込むブロック数
            
        Raises:
            ValueError: パラメータが無効な場合
        """
        # パラメータ検証
        if chunk_size_blocks <= 0:
            raise ValueError(f"チャンクサイズは正の値である必要があります: {chunk_size_blocks}")
        if cluster_size_chunks <= 0:
            raise ValueError(f"クラスタサイズは正の値である必要があります: {cluster_size_chunks}")
        if cache_size_blocks <= 0:
            raise ValueError(f"キャッシュサイズは正の値である必要があります: {cache_size_blocks}")
        if prefetch_window_blocks <= 0:
            raise ValueError(f"プリフェッチ窓は正の値である必要があります: {prefetch_window_blocks}")
        
        self.chunk_size = chunk_size_blocks
        self.cluster_size = cluster_size_chunks
        self.prefetch_window = prefetch_window_blocks
        
        # コンポーネント初期化
        self.cache = LRUCache(cache_size_blocks)
        self.cluster_manager = ClusterManager(cluster_size_chunks)
        
        # 統計情報
        self.total_accesses = 0
        self.cache_hits = 0
        self.previous_chunk_id: Optional[int] = None
        
        logging.info(f"CluMPSimulator初期化完了: "
                    f"chunk={chunk_size_blocks}, cluster={cluster_size_chunks}, "
                    f"cache={cache_size_blocks}, prefetch_window={prefetch_window_blocks}")
    
    def _get_chunk_id(self, block_id: int) -> int:
        """
        ブロックIDからチャンクIDを計算
        
        Args:
            block_id: ブロックID
            
        Returns:
            int: チャンクID
            
        Note:
            チャンクID = ブロックID ÷ チャンクサイズ（整数除算）
            例: ブロック8、チャンクサイズ4 → チャンク2
        """
        return block_id // self.chunk_size
    
    def _prefetch_chunk(self, chunk_id: int) -> None:
        """
        指定されたチャンクをプリフェッチ
        
        予測されたチャンクの開始ブロックから、プリフェッチ窓サイズ分の
        ブロックを事前に読み込んでキャッシュに格納する。
        
        Args:
            chunk_id: プリフェッチ対象のチャンクID
            
        Note:
            プリフェッチ窓がチャンクサイズより大きい場合、
            次のチャンクにまたがってプリフェッチを実行
        """
        start_block = chunk_id * self.chunk_size
        prefetched_blocks = []
        
        for offset in range(self.prefetch_window):
            prefetch_block = start_block + offset
            self.cache.insert(prefetch_block, is_prefetch=True)
            prefetched_blocks.append(prefetch_block)
        
        logging.debug(f"チャンク {chunk_id} をプリフェッチ: ブロック {prefetched_blocks}")
    
    def process_access(self, block_id: int) -> bool:
        """
        アクセス処理（要件定義書のアルゴリズム処理フローに従う）
        
        CluMPアルゴリズムの中核処理。単一ブロックアクセスに対して、
        キャッシュ確認、学習更新、予測プリフェッチの全工程を実行。
        
        Args:
            block_id: アクセス対象のブロックID
            
        Returns:
            bool: キャッシュヒットしたかどうか
            
        Algorithm:
        1. キャッシュアクセス → ヒット/ミス判定
        2. ミスの場合 → ブロック読み込み、キャッシュ挿入
        3. マルコフ連鎖学習 → 前チャンクからの遷移を記録
        4. 次チャンク予測 → CN1から予測、プリフェッチ実行
        """
        self.total_accesses += 1
        current_chunk_id = self._get_chunk_id(block_id)
        
        # 1. アクセス処理：キャッシュを確認し、ヒット/ミスを判定
        cache_hit = self.cache.access(block_id)
        
        if cache_hit:
            self.cache_hits += 1
            logging.debug(f"キャッシュヒット: ブロック {block_id} (チャンク {current_chunk_id})")
            
            # 3. MC更新：「前チャンク → 現チャンク」の遷移を更新
            self._update_markov_chain(current_chunk_id)
            self.previous_chunk_id = current_chunk_id
            return True
        
        # 2. キャッシュ更新：ミスならブロックを読み込み、LRU方式で管理
        self.cache.insert(block_id, is_prefetch=False)
        logging.debug(f"キャッシュミス: ブロック {block_id} を読み込み (チャンク {current_chunk_id})")
        
        # 3. MC更新：「前チャンク → 現チャンク」の遷移を更新
        self._update_markov_chain(current_chunk_id)
        
        self.previous_chunk_id = current_chunk_id
        
        # 4. 予測・プリフェッチ：CN1を参照し、予測チャンクをPrefetchWindow分ロード
        self._execute_prediction_and_prefetch(current_chunk_id)
        
        return False
    
    def _update_markov_chain(self, current_chunk_id: int) -> None:
        """
        マルコフ連鎖の学習更新
        
        Args:
            current_chunk_id: 現在のチャンクID
        """
        if (self.previous_chunk_id is not None and 
            self.previous_chunk_id != current_chunk_id):
            mc_row = self.cluster_manager.get_mc_row(self.previous_chunk_id, allocate=True)
            mc_row.update_transition(current_chunk_id)
            logging.debug(f"遷移学習: チャンク {self.previous_chunk_id} → {current_chunk_id}")
    
    def _execute_prediction_and_prefetch(self, current_chunk_id: int) -> None:
        """
        予測とプリフェッチの実行
        
        Args:
            current_chunk_id: 現在のチャンクID
        """
        mc_row = self.cluster_manager.get_mc_row(current_chunk_id, allocate=False)
        if mc_row is not None:
            predicted_chunk = mc_row.predict_next_chunk()
            if predicted_chunk is not None:
                self._prefetch_chunk(predicted_chunk)
                logging.debug(f"予測プリフェッチ: チャンク {current_chunk_id} → {predicted_chunk}")
    
    def get_evaluation_metrics(self) -> Dict[str, Any]:
        """
        評価指標を計算（要件定義書準拠）
        
        Returns:
            Dict[str, Any]: 評価指標の辞書
        """
        prefetch_stats = self.cache.get_prefetch_stats()
        
        # ヒット率
        hit_rate = self.cache_hits / self.total_accesses if self.total_accesses > 0 else 0.0
        
        # プリフェッチ効率
        prefetch_efficiency = (prefetch_stats["prefetch_used"] / 
                             prefetch_stats["prefetch_total"]) if prefetch_stats["prefetch_total"] > 0 else 0.0
        
        return {
            # 基本統計
            "total_accesses": self.total_accesses,
            "cache_hits": self.cache_hits,
            "hit_rate": hit_rate,
            
            # プリフェッチ統計（要件定義書準拠）
            "prefetch_total": prefetch_stats["prefetch_total"],
            "prefetch_used": prefetch_stats["prefetch_used"],
            "prefetch_unused_evicted": prefetch_stats["prefetch_unused_evicted"],
            "prefetch_efficiency": prefetch_efficiency,
            
            # メモリ消費（生成されたMCRow数）
            "memory_usage_mc_rows": self.cluster_manager.get_memory_usage(),
            
            # パラメータ情報
            "chunk_size": self.chunk_size,
            "cluster_size": self.cluster_size,
            "cache_size": self.cache.cache_size,
            "prefetch_window": self.prefetch_window
        }


class TraceGenerator:
    """
    合成トレース生成器
    要件定義書に基づく入力データ生成
    """
    
    @staticmethod
    def generate_synthetic_trace(n_events: int = 20000, num_files: int = 50,
                               avg_file_length_blocks: int = 200,
                               sequential_prob: float = 0.6,
                               jump_prob: float = 0.1) -> List[int]:
        """
        合成ワークロードを生成
        
        Args:
            n_events: 生成するアクセスイベント数
            num_files: ファイル数
            avg_file_length_blocks: ファイルの平均長（ブロック数）
            sequential_prob: 順次アクセス確率
            jump_prob: 同一ファイル内ランダムジャンプ確率
            
        Returns:
            List[int]: ブロックIDのリスト
        """
        # ファイル配置の設定
        files = []
        base_block = 0
        
        for _ in range(num_files):
            length = max(10, int(random.expovariate(1/avg_file_length_blocks)))
            files.append((base_block, base_block + length - 1))
            base_block += length + random.randint(1, 50)  # ファイル間ギャップ
        
        # アクセストレース生成
        trace = []
        current_file_idx = random.randrange(num_files)
        current_block = random.randrange(files[current_file_idx][0], 
                                       files[current_file_idx][1] + 1)
        
        for _ in range(n_events):
            prob = random.random()
            
            if prob < sequential_prob:
                # 順次アクセス
                if current_block < files[current_file_idx][1]:
                    current_block += 1
                else:
                    # ファイル末尾なら別ファイルにジャンプ
                    current_file_idx = random.randrange(num_files)
                    current_block = random.randrange(files[current_file_idx][0], 
                                                   files[current_file_idx][1] + 1)
            elif prob < sequential_prob + jump_prob:
                # 同一ファイル内ランダムジャンプ
                current_block = random.randrange(files[current_file_idx][0], 
                                               files[current_file_idx][1] + 1)
            else:
                # 別ファイルにジャンプ
                current_file_idx = random.randrange(num_files)
                current_block = random.randrange(files[current_file_idx][0], 
                                               files[current_file_idx][1] + 1)
            
            trace.append(current_block)
        
        return trace


def run_clump_simulation(trace: List[int], chunk_size: int = 8, 
                        cluster_size: int = 32, cache_size: int = 4096,
                        prefetch_window: int = 16) -> Dict[str, Any]:
    """
    CluMPシミュレーションを実行
    
    Args:
        trace: ブロックアクセストレース
        chunk_size: チャンクサイズ（ブロック数）
        cluster_size: クラスタサイズ（チャンク数）
        cache_size: キャッシュ容量（ブロック数）
        prefetch_window: プリフェッチ窓サイズ（ブロック数）
        
    Returns:
        Dict[str, Any]: 評価指標
    """
    simulator = CluMPSimulator(chunk_size, cluster_size, cache_size, prefetch_window)
    
    # トレースを順次処理
    for block_id in trace:
        simulator.process_access(block_id)
    
    return simulator.get_evaluation_metrics()


def get_simulation_config() -> Dict[str, Any]:
    """
    ユーザーからシミュレーション設定を取得
    
    Returns:
        Dict[str, Any]: シミュレーション設定
    """
    print("\n🔧 CluMP シミュレーション設定")
    print("-" * 50)
    
    # デフォルト設定
    config = {
        "trace": {
            "n_events": 50000,
            "num_files": 80,
            "avg_file_length_blocks": 150,
            "sequential_prob": 0.55,
            "jump_prob": 0.15
        },
        "clump": {
            "chunk_size": 32,
            "cluster_size": 32,
            "cache_size": 4096,
            "prefetch_window": 16
        }
    }
    
    print("実行モードを選択してください:")
    print("1. デフォルト設定で実行")
    print("2. カスタム設定で実行")
    print("3. クイック実行（小規模テスト）")
    
    try:
        choice = input("\n選択してください (1-3, デフォルト: 1): ").strip()
        
        if choice == "2":
            print("\n📊 トレース設定")
            config["trace"]["n_events"] = int(input(f"アクセス数 (デフォルト: {config['trace']['n_events']:,}): ") or config["trace"]["n_events"])
            config["trace"]["num_files"] = int(input(f"ファイル数 (デフォルト: {config['trace']['num_files']}): ") or config["trace"]["num_files"])
            config["trace"]["avg_file_length_blocks"] = int(input(f"平均ファイルサイズ(ブロック) (デフォルト: {config['trace']['avg_file_length_blocks']}): ") or config["trace"]["avg_file_length_blocks"])
            config["trace"]["sequential_prob"] = float(input(f"順次アクセス確率 (0.0-1.0, デフォルト: {config['trace']['sequential_prob']}): ") or config["trace"]["sequential_prob"])
            config["trace"]["jump_prob"] = float(input(f"ジャンプ確率 (0.0-1.0, デフォルト: {config['trace']['jump_prob']}): ") or config["trace"]["jump_prob"])
            
            print("\n⚙️ CluMPパラメータ設定")
            config["clump"]["chunk_size"] = int(input(f"チャンクサイズ (ブロック数, デフォルト: {config['clump']['chunk_size']}): ") or config["clump"]["chunk_size"])
            config["clump"]["cluster_size"] = int(input(f"クラスタサイズ (チャンク数, デフォルト: {config['clump']['cluster_size']}): ") or config["clump"]["cluster_size"])
            config["clump"]["cache_size"] = int(input(f"キャッシュサイズ (ブロック数, デフォルト: {config['clump']['cache_size']:,}): ") or config["clump"]["cache_size"])
            config["clump"]["prefetch_window"] = int(input(f"プリフェッチ窓サイズ (ブロック数, デフォルト: {config['clump']['prefetch_window']}): ") or config["clump"]["prefetch_window"])
            
        elif choice == "3":
            # クイック実行設定
            config["trace"]["n_events"] = 10000
            config["trace"]["num_files"] = 20
            config["trace"]["avg_file_length_blocks"] = 50
            config["clump"]["cache_size"] = 2048
            print("クイック実行モード: 小規模設定で高速実行")
            
    except (ValueError, KeyboardInterrupt):
        print("\n⚠️ 入力エラーまたはキャンセル。デフォルト設定を使用します。")
    
    return config


def print_config_summary(config: Dict[str, Any]) -> None:
    """設定サマリーを表示"""
    print("\n📋 シミュレーション設定サマリー")
    print("-" * 50)
    trace = config["trace"]
    clump = config["clump"]
    
    print(f"📊 トレース:")
    print(f"   アクセス数: {trace['n_events']:,}")
    print(f"   ファイル数: {trace['num_files']}")
    print(f"   平均ファイルサイズ: {trace['avg_file_length_blocks']} ブロック")
    print(f"   順次アクセス確率: {trace['sequential_prob']:.1%}")
    print(f"   ジャンプ確率: {trace['jump_prob']:.1%}")
    
    print(f"\n⚙️ CluMPパラメータ:")
    print(f"   チャンクサイズ: {clump['chunk_size']} ブロック")
    print(f"   クラスタサイズ: {clump['cluster_size']} チャンク")
    print(f"   キャッシュサイズ: {clump['cache_size']:,} ブロック")
    print(f"   プリフェッチ窓: {clump['prefetch_window']} ブロック")


def print_evaluation_results(results: Dict[str, Any]) -> None:
    """
    評価結果を表示
    
    Args:
        results: 評価指標の辞書
    """
    print("\n" + "=" * 60)
    print("CluMP シミュレーション結果")
    print("=" * 60)
    
    print(f"📈 基本統計:")
    print(f"   総アクセス数: {results['total_accesses']:,}")
    print(f"   キャッシュヒット数: {results['cache_hits']:,}")
    print(f"   ヒット率: {results['hit_rate']:.3f} ({results['hit_rate']*100:.1f}%)")
    
    print(f"\n🎯 プリフェッチ統計:")
    print(f"   プリフェッチ総数: {results['prefetch_total']:,}")
    print(f"   プリフェッチ使用数: {results['prefetch_used']:,}")
    print(f"   未使用で追い出し: {results['prefetch_unused_evicted']:,}")
    print(f"   プリフェッチ効率: {results['prefetch_efficiency']:.3f} ({results['prefetch_efficiency']*100:.1f}%)")
    
    print(f"\n💾 メモリ消費:")
    print(f"   MC行数: {results['memory_usage_mc_rows']:,}")
    
    print(f"\n⚙️ パラメータ設定:")
    print(f"   チャンクサイズ: {results['chunk_size']} ブロック")
    print(f"   クラスタサイズ: {results['cluster_size']} チャンク")
    print(f"   キャッシュサイズ: {results['cache_size']:,} ブロック")
    print(f"   プリフェッチ窓: {results['prefetch_window']} ブロック")
    
    # 簡易性能評価
    if results['hit_rate'] >= 0.7:
        performance = "優秀 🌟"
    elif results['hit_rate'] >= 0.5:
        performance = "良好 👍"
    elif results['hit_rate'] >= 0.3:
        performance = "普通 😐"
    else:
        performance = "要改善 😞"
    
    print(f"\n🏆 性能評価: {performance}")
    print("=" * 60)


def run_custom_simulation() -> None:
    """カスタムパラメータでの単一シミュレーション実行"""
    print("\n🚀 カスタムCluMPシミュレーション")
    print("-" * 50)
    
    try:
        # パラメータ入力
        chunk_size = int(input("チャンクサイズ (ブロック数, デフォルト: 8): ") or "8")
        cluster_size = int(input("クラスタサイズ (チャンク数, デフォルト: 32): ") or "32")
        cache_size = int(input("キャッシュサイズ (ブロック数, デフォルト: 4096): ") or "4096")
        prefetch_window = int(input("プリフェッチ窓 (ブロック数, デフォルト: 16): ") or "16")
        n_events = int(input("アクセス数 (デフォルト: 10000): ") or "10000")
        
        print(f"\n📊 設定確認:")
        print(f"   チャンク: {chunk_size}, クラスタ: {cluster_size}")
        print(f"   キャッシュ: {cache_size:,}, プリフェッチ窓: {prefetch_window}")
        print(f"   アクセス数: {n_events:,}")
        
        # 実行確認
        confirm = input("\nこの設定で実行しますか？ (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("実行をキャンセルしました。")
            return
        
        # 小規模トレース生成
        print("\nトレース生成中...")
        trace = TraceGenerator.generate_synthetic_trace(
            n_events=n_events,
            num_files=20,
            avg_file_length_blocks=50,
            sequential_prob=0.6,
            jump_prob=0.15
        )
        
        # シミュレーション実行
        print("シミュレーション実行中...")
        start_time = time.time()
        results = run_clump_simulation(
            trace=trace,
            chunk_size=chunk_size,
            cluster_size=cluster_size,
            cache_size=cache_size,
            prefetch_window=prefetch_window
        )
        execution_time = time.time() - start_time
        
        # 結果表示
        print_evaluation_results(results)
        print(f"\n⏱️ 実行時間: {execution_time:.2f}秒")
        
    except (ValueError, KeyboardInterrupt):
        print("\n⚠️ 入力エラーまたはキャンセルされました。")


if __name__ == "__main__":
    # 再現可能な結果のため乱数シードを固定
    random.seed(42)
    
    print("CluMP シミュレータ（要件定義書準拠版）")
    print("=" * 60)
    
    print("\n実行モードを選択してください:")
    print("1. 標準シミュレーション（設定可能）")
    print("2. カスタムパラメータ実験（簡易版）")
    print("3. デモ実行（固定設定）")
    
    try:
        mode = input("\n選択してください (1-3, デフォルト: 1): ").strip()
        
        if mode == "2":
            run_custom_simulation()
        elif mode == "3":
            # デモ実行
            print("\n🎮 デモ実行（固定設定）")
            trace = TraceGenerator.generate_synthetic_trace(
                n_events=25000,
                num_files=40,
                avg_file_length_blocks=100,
                sequential_prob=0.6,
                jump_prob=0.1
            )
            print(f"トレース生成完了: {len(trace)} アクセス")
            print("CluMPシミュレーション実行中...")
            
            results = run_clump_simulation(
                trace=trace,
                chunk_size=16,
                cluster_size=32,
                cache_size=4096,
                prefetch_window=16
            )
            print_evaluation_results(results)
        else:
            # モード1: 標準シミュレーション
            config = get_simulation_config()
            print_config_summary(config)
            
            # 実行確認
            print("\n" + "=" * 60)
            confirm = input("この設定で実行しますか？ (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("実行をキャンセルしました。")
                exit()
            
            print("\n合成トレースを生成中...")
            trace = TraceGenerator.generate_synthetic_trace(**config["trace"])
            print(f"トレース生成完了: {len(trace)} アクセス")
            print("CluMPシミュレーション実行中...")
            
            start_time = time.time()
            results = run_clump_simulation(trace=trace, **config["clump"])
            execution_time = time.time() - start_time
            
            # 結果表示
            print_evaluation_results(results)
            print(f"\n⏱️ 実行時間: {execution_time:.2f}秒")
            
    except KeyboardInterrupt:
        print("\n\n実行をキャンセルしました。")
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
    
    print("\n🎉 シミュレーション完了！")
