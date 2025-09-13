#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP Performance Evaluation Module
要件定義書に基づく性能評価とパラメータ比較機能

本モジュールは、CluMPアルゴリズムの包括的な性能評価を実行するためのツールセットです。
複数パラメータでの比較実験、ベースライン手法との比較、統計分析、可視化機能を提供します。

主要機能:
1. パラメータ比較実験 - 異なるchunk_size/cluster_sizeでの性能測定
2. ベースライン比較 - Linux read-ahead相当の手法との比較
3. 統計分析 - 実験結果の詳細分析と最適パラメータ特定
4. 可視化レポート - グラフィカルな結果表示（オプション）
5. インタラクティブモード - ユーザーフレンドリーな設定・実行

アーキテクチャ:
    PerformanceEvaluator (主要評価器)
    ├── BaselinePrefetcher (比較用ベースライン)
    ├── CluMPSimulator (clump_simulator.pyから)
    └── CluMPVisualizer (visualization.pyから、オプション)

使用例:
    # 基本的な比較実験
    evaluator = PerformanceEvaluator()
    results = evaluator.compare_parameters(trace, [4, 8, 16], [16, 32, 64])
    analysis = evaluator.analyze_results(results)
    
    # ベースライン比較
    comparison = evaluator.compare_with_baseline(trace, best_params)
"""

import sys
import os
import logging
import time
import statistics
import random
from typing import List, Dict, Any, Tuple, Optional, Union

# パス設定
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# CluMPシミュレータの全機能をインポート
from clump_simulator import *

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 可視化モジュールのインポート（オプション）
try:
    from visualization import CluMPVisualizer
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    print("警告: 可視化ライブラリが利用できません。グラフ生成はスキップされます。")


class BaselinePrefetcher:
    """
    ベースライン比較用のシンプルなプリフェッチャ
    Linux read-aheadの簡易実装
    
    この実装は、従来のLinux read-ahead機能を模擬したベースライン手法です。
    順次アクセスパターンを検出した際に、一定数の後続ブロックを先読みします。
    
    アルゴリズム概要:
    1. アクセス処理: キャッシュヒット/ミス判定
    2. 順次検出: 前回アクセスの+1番ブロックかチェック
    3. 先読み実行: 順次の場合、readahead_size分だけ先読み
    4. LRU管理: キャッシュの置換は通常のLRU方式
    
    CluMPとの違い:
    - 学習機能なし（マルコフ連鎖なし）
    - 単純な順次検出のみ
    - 固定サイズの先読み
    - メモリオーバーヘッドほぼゼロ
    
    Attributes:
        cache (LRUCache): キャッシュ管理オブジェクト
        readahead_size (int): 先読みサイズ（ブロック数）
        total_accesses (int): 総アクセス数
        cache_hits (int): キャッシュヒット数
        last_block (Optional[int]): 前回アクセスしたブロックID
        
    Example:
        >>> baseline = BaselinePrefetcher(cache_size_blocks=4096, readahead_size=8)
        >>> for block_id in trace:
        ...     hit = baseline.process_access(block_id)
        >>> metrics = baseline.get_evaluation_metrics()
        >>> print(f"ヒット率: {metrics['hit_rate']:.3f}")
    """
    
    def __init__(self, cache_size_blocks: int, readahead_size: int = 8):
        """
        ベースラインプリフェッチャを初期化
        
        Args:
            cache_size_blocks (int): キャッシュ容量（ブロック数）
            readahead_size (int): 先読みサイズ（ブロック数、デフォルト: 8）
            
        Raises:
            ValueError: パラメータが不正な場合
            
        Note:
            readahead_sizeは通常4-32の範囲で設定します。
            大きすぎると無駄なプリフェッチが増加し、効率が低下します。
        """
        if cache_size_blocks <= 0:
            raise ValueError(f"cache_size_blocks must be positive, got {cache_size_blocks}")
        if readahead_size <= 0:
            raise ValueError(f"readahead_size must be positive, got {readahead_size}")
            
        self.cache: LRUCache = LRUCache(cache_size_blocks)
        self.readahead_size: int = readahead_size
        self.total_accesses: int = 0
        self.cache_hits: int = 0
        self.last_block: Optional[int] = None
        
        logging.debug(f"BaselinePrefetcher initialized: cache_size={cache_size_blocks}, "
                     f"readahead_size={readahead_size}")
    
    def process_access(self, block_id: int) -> bool:
        """
        アクセス処理（シンプルな順次先読み）
        
        Linux read-aheadの動作を模擬:
        1. キャッシュアクセス確認
        2. ミス時はブロック読み込み
        3. 順次アクセス検出時に先読み実行
        
        Args:
            block_id (int): アクセス対象のブロックID
            
        Returns:
            bool: キャッシュヒットしたかどうか
            
        Raises:
            ValueError: block_idが負の値の場合
            
        Note:
            順次アクセスは「前回アクセス + 1」で判定します。
            より複雑な順次性検出（連続した複数アクセス）は実装していません。
        """
        if block_id < 0:
            raise ValueError(f"block_id must be non-negative, got {block_id}")
            
        self.total_accesses += 1
        
        # キャッシュアクセス確認
        cache_hit = self.cache.access(block_id)
        
        if cache_hit:
            self.cache_hits += 1
            return True
        
        # キャッシュミス: ブロックを読み込み
        self.cache.insert(block_id, is_prefetch=False)
        
        # 順次アクセスの場合、先読み実行
        # Linux read-aheadでは、連続する複数のアクセスで順次性を判定するが、
        # ここでは簡略化して前回+1のアクセスで順次と判定
        if self.last_block is not None and block_id == self.last_block + 1:
            try:
                for i in range(1, self.readahead_size + 1):
                    # 先読みブロックをキャッシュに挿入
                    # ここではブロックIDが範囲外になる可能性は考慮しない
                    # （実際のシステムではファイルサイズ制限などで制御される）
                    self.cache.insert(block_id + i, is_prefetch=True)
            except Exception as e:
                logging.warning(f"Prefetch failed for block {block_id}: {e}")
        
        self.last_block = block_id
        return False
    
    def get_evaluation_metrics(self) -> Dict[str, Any]:
        """
        評価指標を取得
        
        CluMPシミュレータと同じ形式の指標を返します。
        ベースライン手法なので、memory_usage_mc_rowsは常に0です。
        
        Returns:
            Dict[str, Any]: 評価指標辞書
                - total_accesses: 総アクセス数
                - cache_hits: キャッシュヒット数
                - hit_rate: ヒット率 (0.0-1.0)
                - prefetch_total: プリフェッチ総数
                - prefetch_used: プリフェッチ使用数
                - prefetch_unused_evicted: 未使用で退避されたプリフェッチ数
                - prefetch_efficiency: プリフェッチ効率 (0.0-1.0)
                - memory_usage_mc_rows: MC行数（ベースラインでは0）
                
        Note:
            division by zeroを避けるため、分母が0の場合は0.0を返します。
        """
        try:
            prefetch_stats = self.cache.get_prefetch_stats()
            hit_rate = (self.cache_hits / self.total_accesses) if self.total_accesses > 0 else 0.0
            prefetch_efficiency = (prefetch_stats["prefetch_used"] / 
                                 prefetch_stats["prefetch_total"]) if prefetch_stats["prefetch_total"] > 0 else 0.0
            
            return {
                "total_accesses": self.total_accesses,
                "cache_hits": self.cache_hits,
                "hit_rate": hit_rate,
                "prefetch_total": prefetch_stats["prefetch_total"],
                "prefetch_used": prefetch_stats["prefetch_used"],
                "prefetch_unused_evicted": prefetch_stats["prefetch_unused_evicted"],
                "prefetch_efficiency": prefetch_efficiency,
                "memory_usage_mc_rows": 0  # ベースラインはMCRowを使用しない
            }
        except Exception as e:
            logging.error(f"Failed to get evaluation metrics: {e}")
            return {"error": str(e)}


class PerformanceEvaluator:
    """
    性能評価器
    要件定義書に基づく包括的な性能評価を実行
    
    本クラスは、CluMPアルゴリズムの性能を多角的に評価するための中核機能を提供します。
    パラメータ最適化、ベースライン比較、統計分析、可視化レポート生成などを統合して実行できます。
    
    主要機能:
    1. パラメータ比較実験: 複数のchunk_size/cluster_sizeでの性能測定
    2. ベースライン比較: Linux read-ahead相当手法との性能差分析
    3. 統計分析: 平均・分散・最適値などの詳細統計
    4. 可視化レポート: ヒートマップ・推移グラフなどの生成
    5. 実行時間測定: 各実験の処理時間追跡
    
    設計思想:
    - 要件定義書完全準拠: 指定された評価指標を正確に算出
    - 拡張性: 新しい評価手法の追加が容易
    - 再現性: 同じ設定での結果再現が可能
    - ユーザビリティ: 直感的なAPI設計
    
    使用パターン:
    ```python
    # 基本使用例
    evaluator = PerformanceEvaluator()
    
    # パラメータ比較実験
    results = evaluator.compare_parameters(trace, [4, 8, 16], [16, 32, 64])
    analysis = evaluator.analyze_results(results)
    evaluator.print_analysis_report(analysis)
    
    # ベースライン比較
    comparison = evaluator.compare_with_baseline(trace, best_params)
    evaluator.print_baseline_comparison_report(comparison)
    ```
    
    Attributes:
        results_history (List[Dict[str, Any]]): 過去の実験結果履歴
        enable_visualization (bool): 可視化機能の有効性
        visualizer (Optional[CluMPVisualizer]): 可視化オブジェクト
    """
    
    def __init__(self, enable_visualization: bool = True):
        """
        性能評価器を初期化
        
        Args:
            enable_visualization (bool): 可視化機能を有効にするかどうか
                True: matplotlib等が利用可能な場合に可視化機能を有効化
                False: 可視化機能を無効化（数値出力のみ）
                
        Note:
            可視化ライブラリが利用できない環境では、enable_visualization=Trueでも
            自動的に無効化され、警告メッセージが表示されます。
        """
        self.results_history: List[Dict[str, Any]] = []
        self.enable_visualization: bool = enable_visualization and VISUALIZATION_AVAILABLE
        
        if self.enable_visualization:
            try:
                self.visualizer = CluMPVisualizer()
                logging.info("可視化機能が有効になりました。")
            except Exception as e:
                logging.warning(f"可視化オブジェクトの初期化に失敗: {e}")
                self.enable_visualization = False
                self.visualizer = None
        else:
            self.visualizer = None
            if enable_visualization:
                logging.warning("可視化ライブラリが利用できないため、可視化機能は無効化されました。")
        
        logging.info(f"PerformanceEvaluator initialized. Visualization: {self.enable_visualization}")
    
    def compare_parameters(self, trace: List[int], 
                         chunk_sizes: List[int] = [4, 8, 16, 32],
                         cluster_sizes: List[int] = [16, 32, 64, 128],
                         cache_size: int = 4096,
                         prefetch_window: int = 16) -> List[Dict[str, Any]]:
        """
        パラメータ比較実験を実行
        
        複数のchunk_size/cluster_sizeの組み合わせで CluMPシミュレーションを実行し、
        最適なパラメータ設定を特定するための比較実験を行います。
        
        実験設計:
        - 全組み合わせでの総当たり実験（N×M回）
        - 固定パラメータ: cache_size, prefetch_window
        - 可変パラメータ: chunk_size, cluster_size
        - 同一トレースでの公平比較
        
        Args:
            trace (List[int]): 評価用トレース（ブロックアクセス列）
            chunk_sizes (List[int]): テスト対象のチャンクサイズリスト
            cluster_sizes (List[int]): テスト対象のクラスタサイズリスト
            cache_size (int): キャッシュサイズ（固定）
            prefetch_window (int): プリフェッチ窓サイズ（固定）
            
        Returns:
            List[Dict[str, Any]]: 実験結果のリスト
                各要素は以下の情報を含む:
                - chunk_size, cluster_size: 実験パラメータ
                - hit_rate, prefetch_efficiency: 主要性能指標
                - memory_usage_mc_rows: メモリ使用量
                - experiment_id: 実験番号
                - execution_time: 実行時間（秒）
                
        Raises:
            ValueError: パラメータが不正な場合
            RuntimeError: シミュレーション実行に失敗した場合
            
        Example:
            >>> evaluator = PerformanceEvaluator()
            >>> results = evaluator.compare_parameters(
            ...     trace=my_trace,
            ...     chunk_sizes=[4, 8, 16],
            ...     cluster_sizes=[16, 32]
            ... )
            >>> print(f"実験数: {len(results)}")  # 6実験（3×2）
        """
        if not trace:
            raise ValueError("trace cannot be empty")
        if not chunk_sizes or not cluster_sizes:
            raise ValueError("chunk_sizes and cluster_sizes cannot be empty")
        if cache_size <= 0 or prefetch_window <= 0:
            raise ValueError("cache_size and prefetch_window must be positive")
            
        results = []
        total_experiments = len(chunk_sizes) * len(cluster_sizes)
        current_exp = 0
        
        logging.info(f"パラメータ比較実験開始 (総実験数: {total_experiments})")
        print(f"パラメータ比較実験開始 (総実験数: {total_experiments})")
        print("-" * 60)
        
        for chunk_size in chunk_sizes:
            for cluster_size in cluster_sizes:
                current_exp += 1
                print(f"実験 {current_exp}/{total_experiments}: "
                      f"チャンク={chunk_size}, クラスタ={cluster_size}")
                
                try:
                    # CluMPシミュレーション実行
                    start_time = time.time()
                    result = run_clump_simulation(
                        trace=trace,
                        chunk_size=chunk_size,
                        cluster_size=cluster_size,
                        cache_size=cache_size,
                        prefetch_window=prefetch_window
                    )
                    execution_time = time.time() - start_time
                    
                    # 結果に実験情報を追加
                    result.update({
                        "experiment_id": current_exp,
                        "execution_time": execution_time
                    })
                    
                    results.append(result)
                    
                    print(f"  → ヒット率: {result['hit_rate']:.3f}, "
                          f"プリフェッチ効率: {result['prefetch_efficiency']:.3f}, "
                          f"MC行数: {result['memory_usage_mc_rows']}")
                    
                    logging.debug(f"Experiment {current_exp} completed in {execution_time:.2f}s")
                    
                except Exception as e:
                    logging.error(f"Experiment {current_exp} failed: {e}")
                    print(f"  → エラー: {e}")
                    # エラーが発生した実験はスキップして続行
                    continue
        
        self.results_history.extend(results)
        logging.info(f"パラメータ比較実験完了: {len(results)}/{total_experiments} 成功")
        return results
    
    def compare_with_baseline(self, trace: List[int], 
                            clump_params: Optional[Dict[str, int]] = None,
                            baseline_readahead: int = 8) -> Dict[str, Dict[str, Any]]:
        """
        ベースライン手法との比較
        
        CluMPアルゴリズムと従来のLinux read-ahead相当手法を同一トレースで比較し、
        性能差を定量的に分析します。これにより、CluMPの有効性を客観的に評価できます。
        
        比較対象:
        - CluMP: マルコフ連鎖学習ベースのプリフェッチ
        - Baseline: 順次アクセス検出ベースの単純先読み
        
        公平性確保:
        - 同一のキャッシュサイズ
        - 同一のアクセストレース
        - 同じLRU置換ポリシー
        
        Args:
            trace (List[int]): 評価用トレース（ブロックアクセス列）
            clump_params (Optional[Dict[str, int]]): CluMPのパラメータ
                None の場合、デフォルト設定を使用:
                - chunk_size: 8
                - cluster_size: 32
                - cache_size: 4096
                - prefetch_window: 16
            baseline_readahead (int): ベースラインの先読みサイズ
                
        Returns:
            Dict[str, Dict[str, Any]]: 比較結果辞書
                "clump": CluMPの評価結果
                "baseline": ベースラインの評価結果
                
        Raises:
            ValueError: パラメータが不正な場合
            RuntimeError: シミュレーション実行に失敗した場合
            
        Example:
            >>> comparison = evaluator.compare_with_baseline(
            ...     trace=my_trace,
            ...     clump_params={"chunk_size": 16, "cluster_size": 64, 
            ...                  "cache_size": 8192, "prefetch_window": 32}
            ... )
            >>> clump_hit_rate = comparison["clump"]["hit_rate"]
            >>> baseline_hit_rate = comparison["baseline"]["hit_rate"]
            >>> improvement = (clump_hit_rate - baseline_hit_rate) / baseline_hit_rate * 100
            >>> print(f"CluMP improvement: {improvement:.1f}%")
        """
        if not trace:
            raise ValueError("trace cannot be empty")
        if baseline_readahead <= 0:
            raise ValueError("baseline_readahead must be positive")
            
        # デフォルトパラメータ設定
        if clump_params is None:
            clump_params = {
                "chunk_size": 8,
                "cluster_size": 32,
                "cache_size": 4096,
                "prefetch_window": 16
            }
        
        # パラメータ検証
        required_keys = ["chunk_size", "cluster_size", "cache_size", "prefetch_window"]
        for key in required_keys:
            if key not in clump_params or clump_params[key] <= 0:
                raise ValueError(f"clump_params must contain positive {key}")
        
        logging.info(f"ベースライン比較実験開始: CluMP vs Linux read-ahead")
        print("ベースライン比較実験開始")
        print("-" * 40)
        
        try:
            # CluMP実行
            print("CluMP実行中...")
            logging.info(f"Running CluMP with params: {clump_params}")
            clump_start = time.time()
            clump_result = run_clump_simulation(trace=trace, **clump_params)
            clump_time = time.time() - clump_start
            clump_result["execution_time"] = clump_time
            
            # ベースライン実行
            print("ベースライン実行中...")
            logging.info(f"Running baseline with readahead_size: {baseline_readahead}")
            baseline_start = time.time()
            baseline = BaselinePrefetcher(
                cache_size_blocks=clump_params["cache_size"],
                readahead_size=baseline_readahead
            )
            
            for block_id in trace:
                baseline.process_access(block_id)
            
            baseline_result = baseline.get_evaluation_metrics()
            baseline_time = time.time() - baseline_start
            baseline_result["execution_time"] = baseline_time
            
            # エラーチェック
            if "error" in clump_result:
                raise RuntimeError(f"CluMP simulation failed: {clump_result['error']}")
            if "error" in baseline_result:
                raise RuntimeError(f"Baseline simulation failed: {baseline_result['error']}")
            
            comparison_result = {
                "clump": clump_result,
                "baseline": baseline_result
            }
            
            logging.info(f"ベースライン比較完了: CluMP={clump_time:.2f}s, Baseline={baseline_time:.2f}s")
            return comparison_result
            
        except Exception as e:
            logging.error(f"Baseline comparison failed: {e}")
            raise RuntimeError(f"Failed to execute baseline comparison: {e}")
    
    def analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        実験結果を分析
        
        複数の実験結果から統計的分析を行い、最適パラメータの特定と
        性能分布の把握を行います。
        
        分析内容:
        1. 最適・最悪パラメータの特定
        2. 各指標の統計値（平均・分散・範囲）
        3. パラメータ最適化効果の定量化
        4. 外れ値・異常値の検出
        
        Args:
            results (List[Dict[str, Any]]): 実験結果のリスト
                各要素は compare_parameters() の戻り値形式
                
        Returns:
            Dict[str, Any]: 分析結果辞書
                "best_parameters": 最適パラメータとその性能
                "worst_parameters": 最悪パラメータとその性能
                "statistics": 各指標の統計情報
                "optimization_effect": 最適化による改善効果
                
        Raises:
            ValueError: 結果リストが空の場合
            KeyError: 必要なキーが不足している場合
            
        Example:
            >>> analysis = evaluator.analyze_results(param_results)
            >>> best = analysis["best_parameters"]
            >>> print(f"最適設定: chunk={best['chunk_size']}, cluster={best['cluster_size']}")
            >>> print(f"最高ヒット率: {best['hit_rate']:.3f}")
        """
        if not results:
            return {"error": "No results to analyze"}
        
        try:
            # 最適パラメータを特定（ヒット率基準）
            best_result = max(results, key=lambda x: x.get("hit_rate", 0))
            worst_result = min(results, key=lambda x: x.get("hit_rate", 0))
            
            # 統計計算用データ抽出
            hit_rates = [r.get("hit_rate", 0) for r in results]
            prefetch_effs = [r.get("prefetch_efficiency", 0) for r in results]
            mc_rows = [r.get("memory_usage_mc_rows", 0) for r in results]
            exec_times = [r.get("execution_time", 0) for r in results if "execution_time" in r]
            
            # 統計値計算（division by zero対策）
            def safe_stats(data):
                if not data:
                    return {"mean": 0, "max": 0, "min": 0, "std": 0}
                return {
                    "mean": statistics.mean(data),
                    "max": max(data),
                    "min": min(data),
                    "std": statistics.stdev(data) if len(data) > 1 else 0
                }
            
            analysis = {
                "best_parameters": {
                    "chunk_size": best_result.get("chunk_size", 0),
                    "cluster_size": best_result.get("cluster_size", 0),
                    "hit_rate": best_result.get("hit_rate", 0),
                    "prefetch_efficiency": best_result.get("prefetch_efficiency", 0),
                    "mc_rows": best_result.get("memory_usage_mc_rows", 0)
                },
                "worst_parameters": {
                    "chunk_size": worst_result.get("chunk_size", 0),
                    "cluster_size": worst_result.get("cluster_size", 0),
                    "hit_rate": worst_result.get("hit_rate", 0)
                },
                "statistics": {
                    "hit_rate": safe_stats(hit_rates),
                    "prefetch_efficiency": safe_stats(prefetch_effs),
                    "mc_rows": safe_stats(mc_rows),
                    "execution_time": safe_stats(exec_times)
                }
            }
            
            # 最適化効果の計算
            min_hit_rate = analysis["statistics"]["hit_rate"]["min"]
            max_hit_rate = analysis["statistics"]["hit_rate"]["max"]
            if min_hit_rate > 0:
                improvement = ((max_hit_rate - min_hit_rate) / min_hit_rate * 100)
                analysis["optimization_effect"] = {
                    "hit_rate_improvement_percent": improvement
                }
            else:
                analysis["optimization_effect"] = {"hit_rate_improvement_percent": 0}
            
            logging.info(f"Results analysis completed: {len(results)} experiments analyzed")
            return analysis
            
        except Exception as e:
            logging.error(f"Failed to analyze results: {e}")
            return {"error": f"Analysis failed: {e}"}
    
    def print_analysis_report(self, analysis: Dict[str, Any]) -> None:
        """
        分析結果レポートを出力
        
        実験結果の分析から得られた知見を、読みやすい形式で出力します。
        最適パラメータ、統計情報、最適化効果などを包括的に表示します。
        
        Args:
            analysis (Dict[str, Any]): analyze_results()の戻り値
                
        Note:
            このメソッドは標準出力への出力のみを行います。
            ファイル出力が必要な場合は、別途実装してください。
        """
        if "error" in analysis:
            print(f"\n❌ 分析エラー: {analysis['error']}")
            return
            
        try:
            print("\n" + "=" * 80)
            print("CluMP パラメータ分析レポート")
            print("=" * 80)
            
            # 最適パラメータ情報
            best = analysis["best_parameters"]
            print(f"\n🏆 最適パラメータ:")
            print(f"   チャンクサイズ: {best['chunk_size']} ブロック")
            print(f"   クラスタサイズ: {best['cluster_size']} チャンク")
            print(f"   ヒット率: {best['hit_rate']:.3f} ({best['hit_rate']*100:.1f}%)")
            print(f"   プリフェッチ効率: {best['prefetch_efficiency']:.3f} ({best['prefetch_efficiency']*100:.1f}%)")
            print(f"   MC行数: {best['mc_rows']:,}")
            
            # 統計情報
            stats = analysis["statistics"]
            print(f"\n📊 性能統計:")
            print(f"   ヒット率: {stats['hit_rate']['mean']:.3f} ± {stats['hit_rate']['std']:.3f}")
            print(f"   　　範囲: {stats['hit_rate']['min']:.3f} - {stats['hit_rate']['max']:.3f}")
            print(f"   プリフェッチ効率: {stats['prefetch_efficiency']['mean']:.3f} ± {stats['prefetch_efficiency']['std']:.3f}")
            print(f"   　　範囲: {stats['prefetch_efficiency']['min']:.3f} - {stats['prefetch_efficiency']['max']:.3f}")
            print(f"   MC行数: {stats['mc_rows']['mean']:.0f} ± {stats['mc_rows']['std']:.0f}")
            print(f"   　範囲: {stats['mc_rows']['min']} - {stats['mc_rows']['max']}")
            
            # 実行時間統計（利用可能な場合）
            if "execution_time" in stats and stats["execution_time"]["mean"] > 0:
                print(f"   実行時間: {stats['execution_time']['mean']:.2f} ± {stats['execution_time']['std']:.2f} 秒")
                print(f"   　　範囲: {stats['execution_time']['min']:.2f} - {stats['execution_time']['max']:.2f} 秒")
            
            # 最適化効果
            if "optimization_effect" in analysis:
                improvement = analysis["optimization_effect"]["hit_rate_improvement_percent"]
                print(f"\n📈 最適化効果:")
                print(f"   パラメータ最適化によるヒット率向上: {improvement:.1f}%")
                
                # パフォーマンス解釈
                if improvement > 20:
                    print(f"   💡 解釈: パラメータ調整による大幅な性能向上が期待できます")
                elif improvement > 10:
                    print(f"   💡 解釈: パラメータ調整による中程度の性能向上が見込めます")
                elif improvement > 5:
                    print(f"   💡 解釈: パラメータ調整による軽微な性能向上があります")
                else:
                    print(f"   💡 解釈: パラメータによる性能差は小さく、デフォルト設定で十分です")
            
            # 最悪パラメータ（参考情報）
            if "worst_parameters" in analysis:
                worst = analysis["worst_parameters"]
                print(f"\n⚠️  最悪パラメータ（参考）:")
                print(f"   チャンクサイズ: {worst['chunk_size']}, クラスタサイズ: {worst['cluster_size']}")
                print(f"   ヒット率: {worst['hit_rate']:.3f} ({worst['hit_rate']*100:.1f}%)")
            
            print("\n" + "=" * 80)
            
        except Exception as e:
            logging.error(f"Failed to print analysis report: {e}")
            print(f"\n❌ レポート出力エラー: {e}")
    
    def print_baseline_comparison_report(self, comparison: Dict[str, Dict[str, Any]]) -> None:
        """
        ベースライン比較レポートを出力
        
        CluMPとベースライン手法の比較結果を詳細に表示します。
        各指標での改善率や実用性の分析も含めて出力します。
        
        Args:
            comparison (Dict[str, Dict[str, Any]]): compare_with_baseline()の戻り値
                "clump": CluMPの実行結果
                "baseline": ベースライン手法の実行結果
                
        Note:
            改善率の計算では、ベースライン手法を基準（100%）とした相対値で表示します。
        """
        if "clump" not in comparison or "baseline" not in comparison:
            print(f"\n❌ 比較データが不完全です")
            return
            
        try:
            clump = comparison["clump"]
            baseline = comparison["baseline"]
            
            # エラーチェック
            if "error" in clump:
                print(f"\n❌ CluMP実行エラー: {clump['error']}")
                return
            if "error" in baseline:
                print(f"\n❌ ベースライン実行エラー: {baseline['error']}")
                return
            
            print("\n" + "=" * 80)
            print("CluMP vs ベースライン比較レポート")
            print("=" * 80)
            
            # ヒット率比較
            print(f"\n📈 ヒット率比較:")
            print(f"   CluMP:      {clump['hit_rate']:.3f} ({clump['hit_rate']*100:.1f}%)")
            print(f"   ベースライン: {baseline['hit_rate']:.3f} ({baseline['hit_rate']*100:.1f}%)")
            
            if baseline['hit_rate'] > 0:
                hit_improvement = ((clump['hit_rate'] - baseline['hit_rate']) / baseline['hit_rate'] * 100)
                print(f"   改善率:      {hit_improvement:+.1f}%")
                
                # 改善効果の解釈
                if hit_improvement > 25:
                    print(f"   💡 CluMPは大幅な性能向上を実現しています")
                elif hit_improvement > 15:
                    print(f"   💡 CluMPは中程度の性能向上を達成しています")
                elif hit_improvement > 5:
                    print(f"   💡 CluMPは軽微な性能向上をもたらしています")
                elif hit_improvement > -5:
                    print(f"   💡 両手法の性能はほぼ同等です")
                else:
                    print(f"   ⚠️  このケースではベースライン手法の方が優秀です")
            else:
                print(f"   ⚠️  ベースラインのヒット率が0のため、改善率を計算できません")
            
            # プリフェッチ効率比較
            print(f"\n🎯 プリフェッチ効率比較:")
            print(f"   CluMP:      {clump['prefetch_efficiency']:.3f} ({clump['prefetch_efficiency']*100:.1f}%)")
            print(f"   ベースライン: {baseline['prefetch_efficiency']:.3f} ({baseline['prefetch_efficiency']*100:.1f}%)")
            
            if baseline['prefetch_efficiency'] > 0:
                pf_improvement = ((clump['prefetch_efficiency'] - baseline['prefetch_efficiency']) / 
                                baseline['prefetch_efficiency'] * 100)
                print(f"   改善率:      {pf_improvement:+.1f}%")
            else:
                if clump['prefetch_efficiency'] > 0:
                    print(f"   改善率:      +∞% (ベースラインで先読み未実行)")
                else:
                    print(f"   改善率:      N/A (両手法とも先読み未実行)")
            
            # メモリ使用量
            print(f"\n💾 メモリ使用量:")
            print(f"   CluMP MC行数: {clump['memory_usage_mc_rows']:,}")
            print(f"   ベースライン: 0 (MCRowなし)")
            
            if clump['memory_usage_mc_rows'] > 0:
                # MC行あたりの性能向上を計算
                hit_gain = clump['hit_rate'] - baseline['hit_rate']
                if hit_gain > 0:
                    efficiency = hit_gain / clump['memory_usage_mc_rows'] * 1000
                    print(f"   効率指標: {efficiency:.3f} (ヒット率向上/1000MC行)")
                else:
                    print(f"   効率指標: N/A (ヒット率向上なし)")
            
            # 詳細統計
            print(f"\n📊 詳細統計:")
            print(f"   総アクセス数: {clump.get('total_accesses', 'N/A'):,}")
            print(f"   CluMP プリフェッチ: 総数={clump['prefetch_total']:,}, 使用数={clump['prefetch_used']:,}")
            print(f"   ベースライン プリフェッチ: 総数={baseline['prefetch_total']:,}, 使用数={baseline['prefetch_used']:,}")
            
            # 実行時間比較（利用可能な場合）
            if "execution_time" in clump and "execution_time" in baseline:
                print(f"\n⏱️  実行時間比較:")
                print(f"   CluMP: {clump['execution_time']:.3f} 秒")
                print(f"   ベースライン: {baseline['execution_time']:.3f} 秒")
                
                if baseline['execution_time'] > 0:
                    time_ratio = clump['execution_time'] / baseline['execution_time']
                    print(f"   時間比: {time_ratio:.2f}x")
                    if time_ratio > 1.5:
                        print(f"   💡 CluMPは学習オーバーヘッドにより実行時間が長めです")
                    elif time_ratio > 1.1:
                        print(f"   💡 CluMPの実行時間オーバーヘッドは許容範囲内です")
                    else:
                        print(f"   💡 両手法の実行時間はほぼ同等です")
            
            # 総合評価
            print(f"\n🏁 総合評価:")
            if baseline['hit_rate'] > 0:
                total_gain = ((clump['hit_rate'] - baseline['hit_rate']) / baseline['hit_rate'] * 100)
                if total_gain > 20:
                    print(f"   ⭐⭐⭐ CluMPは明確な性能優位性を示しています（+{total_gain:.1f}%）")
                elif total_gain > 10:
                    print(f"   ⭐⭐ CluMPは有効な性能向上を達成しています（+{total_gain:.1f}%）")
                elif total_gain > 0:
                    print(f"   ⭐ CluMPは軽微な改善をもたらしています（+{total_gain:.1f}%）")
                else:
                    print(f"   ⚠️ このワークロードではCluMPの効果は限定的です（{total_gain:.1f}%）")
            
            print("\n" + "=" * 80)
            
        except Exception as e:
            logging.error(f"Failed to print baseline comparison report: {e}")
            print(f"\n❌ 比較レポート出力エラー: {e}")


def get_user_config() -> Dict[str, Any]:
    """
    ユーザーからシミュレーション設定を取得
    
    インタラクティブなコマンドライン入力により、ユーザーが実験設定を
    カスタマイズできるようにします。デフォルト設定も提供し、
    入力エラーに対する堅牢性も確保しています。
    
    設定可能項目:
    1. トレース設定: アクセス数、ファイル数、アクセスパターン確率
    2. CluMPパラメータ: チャンク/クラスタサイズ、キャッシュサイズ
    3. ベースライン設定: 先読みサイズ
    
    Returns:
        Dict[str, Any]: ユーザー設定辞書
            "trace": トレース生成パラメータ
            "parameters": CluMPアルゴリズムパラメータ  
            "baseline": ベースライン手法パラメータ
            
    Note:
        入力エラーやキャンセル（Ctrl+C）の場合、デフォルト設定を返します。
        すべての入力は検証され、不正な値の場合はデフォルト値が使用されます。
        
    Example:
        >>> config = get_user_config()
        >>> print(f"実験数: {len(config['parameters']['chunk_sizes']) * len(config['parameters']['cluster_sizes'])}")
    """
    print("\n🔧 シミュレーション設定")
    print("-" * 40)
    
    # デフォルト設定（研究に適した標準的な値）
    config = {
        "trace": {
            "n_events": 15000,      # 十分な学習期間を確保
            "num_files": 60,        # 多様なアクセスパターン
            "avg_file_length_blocks": 120,  # 実用的なファイルサイズ
            "sequential_prob": 0.6,  # 順次アクセス優勢（実環境に近い）
            "jump_prob": 0.15       # 適度なランダムアクセス
        },
        "parameters": {
            "chunk_sizes": [4, 8, 16, 32],    # 幅広いチャンクサイズ検証
            "cluster_sizes": [16, 32, 64],    # 効率的なクラスタサイズ範囲
            "cache_size": 4096,               # 標準的なキャッシュサイズ
            "prefetch_window": 16             # バランスの取れた先読み窓
        },
        "baseline": {
            "readahead_size": 8               # Linux標準的な先読みサイズ
        }
    }
    
    try:
        print("1. デフォルト設定で実行（推奨）")
        print("2. カスタム設定で実行（上級者向け）")
        
        choice = input("\n選択してください (1-2, デフォルト: 1): ").strip()
        
        if choice == "2":
            print("\n📊 トレース設定")
            print("  注意: 大きな値は実行時間が長くなります")
            
            # トレース設定のカスタマイズ
            n_events_input = input(f"アクセス数 (デフォルト: {config['trace']['n_events']}): ").strip()
            if n_events_input and n_events_input.isdigit():
                config["trace"]["n_events"] = max(1000, int(n_events_input))  # 最低1000アクセス
            
            num_files_input = input(f"ファイル数 (デフォルト: {config['trace']['num_files']}): ").strip()
            if num_files_input and num_files_input.isdigit():
                config["trace"]["num_files"] = max(10, int(num_files_input))  # 最低10ファイル
            
            file_length_input = input(f"平均ファイルサイズ(ブロック) (デフォルト: {config['trace']['avg_file_length_blocks']}): ").strip()
            if file_length_input and file_length_input.isdigit():
                config["trace"]["avg_file_length_blocks"] = max(50, int(file_length_input))
            
            seq_prob_input = input(f"順次アクセス確率 (0.0-1.0, デフォルト: {config['trace']['sequential_prob']}): ").strip()
            if seq_prob_input:
                try:
                    seq_prob = float(seq_prob_input)
                    if 0.0 <= seq_prob <= 1.0:
                        config["trace"]["sequential_prob"] = seq_prob
                except ValueError:
                    pass
            
            jump_prob_input = input(f"ジャンプ確率 (0.0-1.0, デフォルト: {config['trace']['jump_prob']}): ").strip()
            if jump_prob_input:
                try:
                    jump_prob = float(jump_prob_input)
                    if 0.0 <= jump_prob <= 1.0:
                        config["trace"]["jump_prob"] = jump_prob
                except ValueError:
                    pass
            
            print("\n⚙️ CluMPパラメータ設定")
            print("  注意: 組み合わせ数が実験時間に影響します")
            
            # CluMPパラメータのカスタマイズ
            chunk_sizes_str = input(f"チャンクサイズ (カンマ区切り, デフォルト: {','.join(map(str, config['parameters']['chunk_sizes']))}): ").strip()
            if chunk_sizes_str:
                try:
                    chunk_sizes = [max(1, int(x.strip())) for x in chunk_sizes_str.split(",") if x.strip().isdigit()]
                    if chunk_sizes:
                        config["parameters"]["chunk_sizes"] = chunk_sizes
                except ValueError:
                    pass
            
            cluster_sizes_str = input(f"クラスタサイズ (カンマ区切り, デフォルト: {','.join(map(str, config['parameters']['cluster_sizes']))}): ").strip()
            if cluster_sizes_str:
                try:
                    cluster_sizes = [max(4, int(x.strip())) for x in cluster_sizes_str.split(",") if x.strip().isdigit()]
                    if cluster_sizes:
                        config["parameters"]["cluster_sizes"] = cluster_sizes
                except ValueError:
                    pass
            
            cache_size_input = input(f"キャッシュサイズ (ブロック数, デフォルト: {config['parameters']['cache_size']}): ").strip()
            if cache_size_input and cache_size_input.isdigit():
                config["parameters"]["cache_size"] = max(1024, int(cache_size_input))  # 最低1024ブロック
            
            prefetch_window_input = input(f"プリフェッチ窓サイズ (デフォルト: {config['parameters']['prefetch_window']}): ").strip()
            if prefetch_window_input and prefetch_window_input.isdigit():
                config["parameters"]["prefetch_window"] = max(4, int(prefetch_window_input))
            
            print("\n🏁 ベースライン設定")
            baseline_input = input(f"ベースライン先読みサイズ (デフォルト: {config['baseline']['readahead_size']}): ").strip()
            if baseline_input and baseline_input.isdigit():
                config["baseline"]["readahead_size"] = max(1, int(baseline_input))
            
    except (ValueError, KeyboardInterrupt):
        print("\n⚠️ 入力エラーまたはキャンセル。デフォルト設定を使用します。")
        logging.info("User input cancelled or invalid, using default configuration")
    
    return config


def print_config_summary(config: Dict[str, Any]) -> None:
    """
    設定サマリーを表示
    
    ユーザーが選択した実験設定を見やすい形式で表示し、
    実行前の最終確認を可能にします。
    
    Args:
        config (Dict[str, Any]): get_user_config()の戻り値
        
    Note:
        実験数の計算も含め、実行時間の見積もりに役立つ情報を提供します。
    """
    print("\n📋 実行設定サマリー")
    print("-" * 40)
    trace = config["trace"]
    params = config["parameters"]
    baseline = config["baseline"]
    
    print(f"📊 トレース:")
    print(f"   アクセス数: {trace['n_events']:,}")
    print(f"   ファイル数: {trace['num_files']}")
    print(f"   平均ファイルサイズ: {trace['avg_file_length_blocks']} ブロック")
    print(f"   順次アクセス確率: {trace['sequential_prob']:.1%}")
    print(f"   ジャンプ確率: {trace['jump_prob']:.1%}")
    
    print(f"\n⚙️ CluMPパラメータ:")
    print(f"   チャンクサイズ: {params['chunk_sizes']}")
    print(f"   クラスタサイズ: {params['cluster_sizes']}")
    print(f"   キャッシュサイズ: {params['cache_size']:,} ブロック")
    print(f"   プリフェッチ窓: {params['prefetch_window']}")
    
    print(f"\n🏁 ベースライン:")
    print(f"   先読みサイズ: {baseline['readahead_size']}")
    
    total_experiments = len(params['chunk_sizes']) * len(params['cluster_sizes'])
    print(f"\n🧪 実験数: {total_experiments} パターン")
    
    # 実行時間の簡易見積もり
    estimated_time = total_experiments * trace['n_events'] / 10000  # 経験的な式
    if estimated_time < 60:
        print(f"⏱️ 推定実行時間: {estimated_time:.1f} 秒")
    elif estimated_time < 3600:
        print(f"⏱️ 推定実行時間: {estimated_time/60:.1f} 分")
    else:
        print(f"⏱️ 推定実行時間: {estimated_time/3600:.1f} 時間")
        print(f"   ⚠️ 長時間の実行が予想されます。設定の見直しを推奨します。")


def quick_simulation(chunk_size: int = 8, cluster_size: int = 32, 
                    cache_size: int = 4096, n_events: int = 5000) -> Dict[str, Any]:
    """
    クイックシミュレーション（単一パラメータセット）
    
    単一のパラメータ設定でCluMPシミュレーションを実行し、
    基本的な動作確認や性能の概要把握を行います。
    
    用途:
    - CluMPの基本動作確認
    - 新しいパラメータの予備評価
    - デモ・教育目的での実行
    - 包括的実験前の事前検証
    
    Args:
        chunk_size (int): チャンクサイズ（ブロック数）
        cluster_size (int): クラスタサイズ（チャンク数）
        cache_size (int): キャッシュサイズ（ブロック数）
        n_events (int): アクセス数
        
    Returns:
        Dict[str, Any]: シミュレーション結果
            run_clump_simulation()と同じ形式
            
    Raises:
        ValueError: パラメータが不正な場合
        RuntimeError: シミュレーション実行に失敗した場合
        
    Example:
        >>> result = quick_simulation(chunk_size=16, cluster_size=64, n_events=10000)
        >>> print(f"ヒット率: {result['hit_rate']:.3f}")
        >>> print(f"MC行数: {result['memory_usage_mc_rows']}")
    """
    # パラメータ検証
    if chunk_size <= 0 or cluster_size <= 0 or cache_size <= 0 or n_events <= 0:
        raise ValueError("All parameters must be positive")
    
    print(f"🚀 クイックシミュレーション実行")
    print(f"   パラメータ: chunk={chunk_size}, cluster={cluster_size}, cache={cache_size}")
    print(f"   アクセス数: {n_events:,}")
    
    try:
        # 合成トレース生成（クイックテスト用の設定）
        trace = TraceGenerator.generate_synthetic_trace(
            n_events=n_events,
            num_files=max(10, n_events // 250),  # アクセス数に応じたファイル数
            avg_file_length_blocks=50,            # 小さめのファイル
            sequential_prob=0.6,                  # 標準的な順次率
            jump_prob=0.15                        # 標準的なジャンプ率
        )
        
        # シミュレーション実行
        logging.info(f"Quick simulation: chunk={chunk_size}, cluster={cluster_size}, "
                    f"cache={cache_size}, events={n_events}")
        
        result = run_clump_simulation(
            trace=trace,
            chunk_size=chunk_size,
            cluster_size=cluster_size,
            cache_size=cache_size,
            prefetch_window=16  # 固定値
        )
        
        print(f"✅ 結果: ヒット率 {result['hit_rate']:.3f}, プリフェッチ効率 {result['prefetch_efficiency']:.3f}")
        logging.info(f"Quick simulation completed: hit_rate={result['hit_rate']:.3f}")
        
        return result
        
    except Exception as e:
        logging.error(f"Quick simulation failed: {e}")
        raise RuntimeError(f"Quick simulation failed: {e}")


def custom_parameter_experiment() -> None:
    """
    カスタムパラメータ実験モード
    
    ユーザーが指定した単一のパラメータセットで詳細な実験を行います。
    quick_simulation()よりも詳細な結果表示と分析を提供します。
    
    機能:
    - インタラクティブなパラメータ入力
    - 詳細な結果表示
    - エラーハンドリング
    - 入力検証
    
    Note:
        この関数は対話型モードでのみ使用されます。
        プログラムからの呼び出しには quick_simulation() を使用してください。
    """
    print("\n🔬 カスタムパラメータ実験モード")
    print("-" * 50)
    
    try:
        # パラメータ入力（検証付き）
        chunk_size_input = input("チャンクサイズ (デフォルト: 8): ").strip()
        chunk_size = max(1, int(chunk_size_input)) if chunk_size_input.isdigit() else 8
        
        cluster_size_input = input("クラスタサイズ (デフォルト: 32): ").strip()
        cluster_size = max(4, int(cluster_size_input)) if cluster_size_input.isdigit() else 32
        
        cache_size_input = input("キャッシュサイズ (デフォルト: 4096): ").strip()
        cache_size = max(1024, int(cache_size_input)) if cache_size_input.isdigit() else 4096
        
        n_events_input = input("アクセス数 (デフォルト: 5000): ").strip()
        n_events = max(1000, int(n_events_input)) if n_events_input.isdigit() else 5000
        
        # 実行時間警告
        if n_events > 50000:
            confirm = input(f"⚠️ アクセス数が多いため実行時間が長くなる可能性があります。続行しますか？ (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("実験をキャンセルしました。")
                return
        
        # シミュレーション実行
        result = quick_simulation(chunk_size, cluster_size, cache_size, n_events)
        
        # 詳細結果表示
        print(f"\n📊 詳細結果:")
        print(f"   総アクセス数: {result['total_accesses']:,}")
        print(f"   キャッシュヒット数: {result['cache_hits']:,}")
        print(f"   ヒット率: {result['hit_rate']:.3f} ({result['hit_rate']*100:.1f}%)")
        print(f"   プリフェッチ総数: {result['prefetch_total']:,}")
        print(f"   プリフェッチ使用数: {result['prefetch_used']:,}")
        print(f"   プリフェッチ効率: {result['prefetch_efficiency']:.3f} ({result['prefetch_efficiency']*100:.1f}%)")
        print(f"   MC行数: {result['memory_usage_mc_rows']:,}")
        
        # 結果の評価コメント
        if result['hit_rate'] > 0.7:
            print(f"\n💡 評価: 優秀なヒット率です。このパラメータ設定は効果的です。")
        elif result['hit_rate'] > 0.5:
            print(f"\n💡 評価: 標準的なヒット率です。さらなる最適化の余地があります。")
        else:
            print(f"\n💡 評価: ヒット率が低めです。パラメータの調整を検討してください。")
            
    except (ValueError, KeyboardInterrupt):
        print("\n⚠️ 入力エラーまたはキャンセルされました。")
        logging.info("Custom parameter experiment cancelled or failed")


def main():
    """
    メイン実行関数
    
    CluMP性能評価システムのエントリーポイントです。
    ユーザーの選択に応じて異なる評価モードを実行し、
    包括的な性能分析を提供します。
    
    実行モード:
    1. 包括的性能評価: パラメータ比較 + ベースライン比較 + 可視化
    2. カスタムパラメータ実験: 単一設定での詳細分析
    3. クイックテスト: デフォルト設定での動作確認
    
    機能:
    - インタラクティブなモード選択
    - 堅牢なエラーハンドリング
    - 詳細な実行ログ
    - 再現性確保（乱数シード固定）
    - 可視化レポート自動生成
    
    Note:
        長時間実行が予想される場合は、事前に警告を表示します。
        すべての実験結果はログに記録され、トラブルシューティングに活用できます。
    """
    print("CluMP 性能評価システム（要件定義書準拠版）")
    print("=" * 60)
    
    logging.info("CluMP Performance Evaluation System started")
    
    print("実行モードを選択してください:")
    print("1. 包括的性能評価（パラメータ比較＋ベースライン比較）")
    print("2. カスタムパラメータ実験（単一設定）")
    print("3. クイックテスト（デフォルト設定）")
    
    try:
        mode = input("\n選択してください (1-3, デフォルト: 1): ").strip()
        
        if mode == "2":
            logging.info("Custom parameter experiment mode selected")
            custom_parameter_experiment()
            return
        elif mode == "3":
            logging.info("Quick test mode selected")
            quick_simulation()
            return
        
        # モード1: 包括的評価
        logging.info("Comprehensive evaluation mode selected")
        
        # ユーザー設定取得
        config = get_user_config()
        print_config_summary(config)
        
        # 実行確認
        print("\n" + "=" * 60)
        confirm = input("この設定で実行しますか？ (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("実行をキャンセルしました。")
            logging.info("Execution cancelled by user")
            return
            
    except KeyboardInterrupt:
        print("\n実行をキャンセルしました。")
        logging.info("Execution cancelled by user (KeyboardInterrupt)")
        return
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}")
        logging.error(f"Unexpected error in mode selection: {e}")
        return
    
    # 実行環境の準備
    # 乱数シード固定（再現性確保）
    random.seed(42)
    logging.info("Random seed set to 42 for reproducibility")
    
    # 合成トレース生成
    print("\n合成トレース生成中...")
    try:
        trace = TraceGenerator.generate_synthetic_trace(**config["trace"])
        print(f"トレース生成完了: {len(trace)} アクセス")
        logging.info(f"Synthetic trace generated: {len(trace)} accesses")
    except Exception as e:
        print(f"❌ トレース生成に失敗しました: {e}")
        logging.error(f"Trace generation failed: {e}")
        return
    
    # 性能評価器初期化
    try:
        evaluator = PerformanceEvaluator()
        logging.info("PerformanceEvaluator initialized successfully")
    except Exception as e:
        print(f"❌ 性能評価器の初期化に失敗しました: {e}")
        logging.error(f"PerformanceEvaluator initialization failed: {e}")
        return
    
    # 1. パラメータ比較実験
    print("\n1. パラメータ比較実験実行中...")
    try:
        param_results = evaluator.compare_parameters(
            trace=trace,
            chunk_sizes=config["parameters"]["chunk_sizes"],
            cluster_sizes=config["parameters"]["cluster_sizes"],
            cache_size=config["parameters"]["cache_size"],
            prefetch_window=config["parameters"]["prefetch_window"]
        )
        
        if not param_results:
            print("⚠️ パラメータ比較実験で有効な結果が得られませんでした。")
            logging.warning("No valid results from parameter comparison")
            return
            
        logging.info(f"Parameter comparison completed: {len(param_results)} experiments")
        
    except Exception as e:
        print(f"❌ パラメータ比較実験に失敗しました: {e}")
        logging.error(f"Parameter comparison failed: {e}")
        return
    
    # パラメータ分析
    try:
        analysis = evaluator.analyze_results(param_results)
        
        if "error" in analysis:
            print(f"❌ 結果分析に失敗しました: {analysis['error']}")
            logging.error(f"Results analysis failed: {analysis['error']}")
            return
            
        evaluator.print_analysis_report(analysis)
        logging.info("Parameter analysis completed successfully")
        
    except Exception as e:
        print(f"❌ 結果分析に失敗しました: {e}")
        logging.error(f"Results analysis failed: {e}")
        return
    
    # 2. ベースライン比較実験
    print("\n\n2. ベースライン比較実験実行中...")
    try:
        best_params = {
            "chunk_size": analysis["best_parameters"]["chunk_size"],
            "cluster_size": analysis["best_parameters"]["cluster_size"],
            "cache_size": config["parameters"]["cache_size"],
            "prefetch_window": config["parameters"]["prefetch_window"]
        }
        
        baseline_comparison = evaluator.compare_with_baseline(
            trace=trace,
            clump_params=best_params,
            baseline_readahead=config["baseline"]["readahead_size"]
        )
        
        # ベースライン比較レポート
        evaluator.print_baseline_comparison_report(baseline_comparison)
        logging.info("Baseline comparison completed successfully")
        
    except Exception as e:
        print(f"❌ ベースライン比較実験に失敗しました: {e}")
        logging.error(f"Baseline comparison failed: {e}")
        # ベースライン比較が失敗しても、パラメータ分析結果は有効なので続行
    
    # 3. 可視化レポート生成（要件定義書の拡張要件）
    if evaluator.enable_visualization:
        print("\n\n3. 可視化レポート生成中...")
        try:
            visualization_files = evaluator.visualizer.create_visualization_report(
                results=param_results,
                analysis=analysis,
                comparison=baseline_comparison if 'baseline_comparison' in locals() else None,
                trace=trace
            )
            print(f"\n📊 可視化レポート生成完了！")
            print(f"生成されたグラフ: {len(visualization_files)} 個")
            for i, path in enumerate(visualization_files, 1):
                print(f"  {i}. {os.path.basename(path)}")
            logging.info(f"Visualization report generated: {len(visualization_files)} files")
            
        except Exception as e:
            print(f"⚠️ 可視化生成中にエラーが発生しました: {e}")
            logging.warning(f"Visualization generation failed: {e}")
            print("数値による分析結果は正常に完了しています。")
    else:
        print("\n可視化機能は無効です。数値による分析のみを実行しました。")
        logging.info("Visualization disabled, numerical analysis only")
    
    # 実行完了
    print("\n✅ 性能評価完了")
    print("\n📋 実行サマリー:")
    print(f"   実行モード: 包括的性能評価")
    print(f"   パラメータ実験: {len(param_results)} 設定")
    print(f"   最適設定: chunk={analysis['best_parameters']['chunk_size']}, "
          f"cluster={analysis['best_parameters']['cluster_size']}")
    print(f"   最高ヒット率: {analysis['best_parameters']['hit_rate']:.3f}")
    
    if 'baseline_comparison' in locals():
        clump_hit = baseline_comparison['clump']['hit_rate']
        baseline_hit = baseline_comparison['baseline']['hit_rate']
        if baseline_hit > 0:
            improvement = (clump_hit - baseline_hit) / baseline_hit * 100
            print(f"   ベースライン比較: {improvement:+.1f}% 改善")
    
    logging.info("Performance evaluation completed successfully")


if __name__ == "__main__":
    main()