#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP Parameter Optimization and Evaluation Script
論文準拠版パラメータ最適化とパフォーマンス評価

論文の結果を再現するためのパラメータ調整とワークロード最適化
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from clump_simulator import *
import random


def parameter_sweep_experiment():
    """
    パラメータスイープ実験（論文Section 4準拠）
    
    論文で有効とされたパラメータ範囲での詳細評価
    """
    print("📊 CluMPパラメータスイープ実験")
    print("=" * 60)
    
    # 論文準拠パラメータ範囲
    chunk_sizes = [4, 8, 16, 32]          # 論文でテストされた範囲
    cluster_sizes = [16, 32, 64, 128]     # 論文でテストされた範囲
    cache_size = 4096
    prefetch_window = 16
    
    # テスト用ワークロード（KVM相当）
    trace = WorkloadGenerator.generate_kvm_workload(total_blocks=15000, block_range=30000)
    
    best_result = None
    best_improvement = 0
    results = []
    
    print(f"テストパラメータ組み合わせ: {len(chunk_sizes) * len(cluster_sizes)}パターン")
    print()
    
    for chunk_size in chunk_sizes:
        for cluster_size in cluster_sizes:
            clump_params = {
                "chunk_size": chunk_size,
                "cluster_size": cluster_size,
                "prefetch_window": prefetch_window
            }
            
            try:
                result = compare_clump_vs_readahead(trace, clump_params, cache_size)
                improvement = result["improvement"]["hit_rate_improvement"]
                
                results.append({
                    "chunk_size": chunk_size,
                    "cluster_size": cluster_size,
                    "clump_hit_rate": result["clump"]["hit_rate"],
                    "readahead_hit_rate": result["readahead"]["hit_rate"],
                    "improvement": improvement,
                    "mc_rows": result["clump"]["memory_usage_mc_rows"],
                    "prefetch_efficiency": result["clump"]["prefetch_efficiency"]
                })
                
                print(f"チャンク={chunk_size:2d}, クラスタ={cluster_size:3d}: "
                      f"CluMP={result['clump']['hit_rate']:.3f}, "
                      f"先読み={result['readahead']['hit_rate']:.3f}, "
                      f"改善={improvement:.2f}x, MC={result['clump']['memory_usage_mc_rows']}")
                
                if improvement > best_improvement:
                    best_improvement = improvement
                    best_result = (chunk_size, cluster_size, result)
                    
            except Exception as e:
                print(f"エラー chunk={chunk_size}, cluster={cluster_size}: {e}")
    
    print("\n🏆 最適パラメータ")
    print("-" * 40)
    if best_result:
        chunk, cluster, result = best_result
        print(f"最適パラメータ: チャンク={chunk}, クラスタ={cluster}")
        print(f"CluMPヒット率: {result['clump']['hit_rate']:.3f}")
        print(f"先読みヒット率: {result['readahead']['hit_rate']:.3f}")
        print(f"改善倍率: {result['improvement']['hit_rate_improvement']:.2f}x")
        print(f"MC行数: {result['clump']['memory_usage_mc_rows']}")
    
    return results, best_result


def optimized_workload_experiment():
    """
    最適化ワークロード実験
    
    論文の結果により近づけるためのワークロード調整
    """
    print("\n🔧 最適化ワークロード実験")
    print("=" * 60)
    
    # 論文で最良とされたパラメータ（推定）
    optimal_params = {
        "chunk_size": 8,      # 小さなチャンクサイズが効果的
        "cluster_size": 128,  # 大きなクラスタサイズが効果的
        "prefetch_window": 32
    }
    
    # より現実的なワークロードパターン（論文準拠）
    workloads = {
        "KVM起動（最適化）": {
            "generator": lambda: generate_realistic_kvm_workload(),
            "target_improvement": 1.91
        },
        "カーネルビルド（最適化）": {
            "generator": lambda: generate_realistic_kernel_workload(),
            "target_improvement": 1.31
        }
    }
    
    for workload_name, config in workloads.items():
        print(f"\n📊 {workload_name}")
        print("-" * 30)
        
        trace = config["generator"]()
        result = compare_clump_vs_readahead(trace, optimal_params)
        
        improvement = result["improvement"]["hit_rate_improvement"]
        target = config["target_improvement"]
        
        print(f"Linux先読み: {result['readahead']['hit_rate']:.3f}")
        print(f"CluMP: {result['clump']['hit_rate']:.3f}")
        print(f"改善倍率: {improvement:.2f}x (目標: {target:.2f}x)")
        print(f"目標達成率: {(improvement/target)*100:.1f}%")
        print(f"MC行数: {result['clump']['memory_usage_mc_rows']}")
        print(f"プリフェッチ効率: {result['clump']['prefetch_efficiency']:.3f}")


def generate_realistic_kvm_workload(total_blocks: int = 10000) -> List[int]:
    """
    より現実的なKVMワークロード生成
    
    実際のVM起動プロセスをより忠実に模擬
    """
    trace = []
    current_block = 0
    
    # Phase 1: ブートローダー読み込み（高い逐次性）
    phase1_blocks = total_blocks // 4
    for _ in range(phase1_blocks):
        trace.append(current_block)
        current_block += 1
    
    # Phase 2: カーネル読み込み（中程度の逐次性とジャンプ）
    phase2_blocks = total_blocks // 3
    for _ in range(phase2_blocks):
        if random.random() < 0.7:  # 70% 逐次
            trace.append(current_block)
            current_block += 1
        else:  # 30% ジャンプ
            current_block += random.randint(10, 100)
            trace.append(current_block)
    
    # Phase 3: システム初期化（混合パターン）
    phase3_blocks = total_blocks - phase1_blocks - phase2_blocks
    for _ in range(phase3_blocks):
        pattern = random.random()
        if pattern < 0.4:  # 逐次アクセス
            trace.append(current_block)
            current_block += 1
        elif pattern < 0.8:  # 小ジャンプ
            current_block += random.randint(1, 20)
            trace.append(current_block)
        else:  # 大ジャンプ
            current_block += random.randint(100, 1000)
            trace.append(current_block)
    
    return trace


def generate_realistic_kernel_workload(total_blocks: int = 25000) -> List[int]:
    """
    より現実的なカーネルビルドワークロード生成
    
    実際のmakeプロセスをより忠実に模擬
    """
    trace = []
    base_blocks = [random.randint(0, 100000) for _ in range(50)]  # ベースファイル位置
    
    for _ in range(total_blocks):
        pattern = random.random()
        
        if pattern < 0.25:  # ソースファイル逐次読み込み
            base = random.choice(base_blocks)
            for i in range(random.randint(5, 50)):
                trace.append(base + i)
                if len(trace) >= total_blocks:
                    break
                    
        elif pattern < 0.65:  # ヘッダーファイルランダムアクセス
            for _ in range(random.randint(1, 10)):
                trace.append(random.randint(0, 200000))
                if len(trace) >= total_blocks:
                    break
                    
        else:  # オブジェクトファイル作成（大きなジャンプ）
            base = random.randint(50000, 150000)
            for i in range(random.randint(10, 100)):
                trace.append(base + i)
                if len(trace) >= total_blocks:
                    break
        
        if len(trace) >= total_blocks:
            break
    
    return trace[:total_blocks]


def detailed_comparison_analysis():
    """
    詳細比較分析
    
    CluMPとLinux先読みの詳細な動作比較
    """
    print("\n🔬 詳細比較分析")
    print("=" * 60)
    
    # 最適パラメータでの詳細テスト
    params = {
        "chunk_size": 8,
        "cluster_size": 64,
        "prefetch_window": 24
    }
    
    # 異なるパターンのワークロード
    test_patterns = {
        "逐次優勢": {
            "sequential_ratio": 0.8,
            "random_ratio": 0.1,
            "jump_ratio": 0.1
        },
        "混合": {
            "sequential_ratio": 0.4,
            "random_ratio": 0.4,
            "jump_ratio": 0.2
        },
        "ランダム優勢": {
            "sequential_ratio": 0.2,
            "random_ratio": 0.6,
            "jump_ratio": 0.2
        }
    }
    
    for pattern_name, ratios in test_patterns.items():
        print(f"\n📊 {pattern_name}パターン")
        print("-" * 25)
        
        trace = generate_pattern_workload(10000, ratios)
        result = compare_clump_vs_readahead(trace, params)
        
        print(f"Linux先読み: {result['readahead']['hit_rate']:.3f}")
        print(f"CluMP: {result['clump']['hit_rate']:.3f}")
        print(f"改善倍率: {result['improvement']['hit_rate_improvement']:.2f}x")
        print(f"プリフェッチ効率 - 先読み: {result['readahead']['prefetch_efficiency']:.3f}")
        print(f"プリフェッチ効率 - CluMP: {result['clump']['prefetch_efficiency']:.3f}")


def generate_pattern_workload(total_blocks: int, ratios: Dict[str, float]) -> List[int]:
    """
    パターン指定ワークロード生成
    """
    trace = []
    current_block = random.randint(0, 50000)
    
    for _ in range(total_blocks):
        pattern = random.random()
        
        if pattern < ratios["sequential_ratio"]:
            # 逐次アクセス
            trace.append(current_block)
            current_block += 1
        elif pattern < ratios["sequential_ratio"] + ratios["random_ratio"]:
            # ランダムアクセス
            current_block = random.randint(0, 100000)
            trace.append(current_block)
        else:
            # ジャンプアクセス
            current_block += random.randint(100, 5000)
            trace.append(current_block)
    
    return trace


if __name__ == "__main__":
    # 乱数シード固定
    random.seed(42)
    
    print("CluMP論文準拠パフォーマンス評価システム")
    print("=" * 70)
    
    # 1. パラメータスイープ実験
    results, best_result = parameter_sweep_experiment()
    
    # 2. 最適化ワークロード実験
    optimized_workload_experiment()
    
    # 3. 詳細比較分析
    detailed_comparison_analysis()
    
    # 4. 可視化機能統合
    print("\n🎨 可視化レポート生成")
    print("=" * 40)
    
    try:
        from visualization import PaperBasedVisualizer
        
        # 可視化器初期化
        visualizer = PaperBasedVisualizer()
        session_dir = visualizer.create_session_directory()
        
        # パラメータスイープ結果を可視化用に変換
        viz_results = {}
        for result in results:
            key = (result["chunk_size"], result["cluster_size"])
            viz_results[key] = {
                'hit_rate': result["clump_hit_rate"],
                'prefetch_efficiency': result["prefetch_efficiency"],
                'memory_usage_mc_rows': result["mc_rows"]
            }
        
        if viz_results:
            # ヒートマップ生成
            print("📊 パラメータ感度ヒートマップ生成中...")
            visualizer.plot_parameter_sensitivity_heatmap(viz_results, 'hit_rate')
            visualizer.plot_parameter_sensitivity_heatmap(viz_results, 'prefetch_efficiency')
            visualizer.plot_parameter_sensitivity_heatmap(viz_results, 'memory_usage_mc_rows')
            
            # メモリオーバーヘッド分析
            print("💾 メモリオーバーヘッド分析生成中...")
            visualizer.plot_memory_overhead_analysis(viz_results)
            
            # ベースライン比較（最適パラメータで）
            if best_result:
                print("📈 ベースライン比較チャート生成中...")
                _, _, best_comparison = best_result
                clump_best = best_comparison['clump']
                readahead_best = best_comparison['readahead']
                visualizer.plot_baseline_comparison(clump_best, readahead_best)
                
                # ヒット率推移（最適パラメータで）
                print("📈 ヒット率推移チャート生成中...")
                test_trace = generate_realistic_kvm_workload(5000)  # 軽量テスト
                visualizer.plot_hit_rate_progression(
                    test_trace,
                    chunk_size=best_result[0],
                    cluster_size=best_result[1]
                )
            
            # 包括的レポート生成
            print("📄 包括的HTMLレポート生成中...")
            report_data = {
                'parameter_results': viz_results,
                'best_parameters': best_result,
                'comparison_results': results
            }
            visualizer.create_comprehensive_report(report_data)
            
            print(f"\n✅ 可視化完了！結果は以下に保存されました:")
            print(f"   📁 {session_dir}")
            print(f"   🌐 HTMLレポート: {session_dir}/comprehensive_report.html")
            
        else:
            print("⚠️  可視化用データが不足しています。")
            
    except ImportError:
        print("⚠️  可視化モジュールをインポートできません。")
        print("pip install matplotlib numpy seaborn を実行してください。")
    except Exception as e:
        print(f"❌ 可視化中にエラーが発生: {e}")
    
    print("\n🎯 実験完了")
    print("=" * 40)
    print("論文目標値:")
    print("- KVM: 1.91x改善 (41.39% → 79.22%)")
    print("- カーネルビルド: 1.31x改善 (59% → 77.25%)")
    print("\n実装改善ポイント:")
    print("1. ワークロードパターンの最適化")
    print("2. チャンクサイズの微調整")
    print("3. プリフェッチ窓サイズの調整")
    print("4. MC学習期間の調整")