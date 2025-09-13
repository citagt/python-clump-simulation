#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP Visualization Module
要件定義書の拡張要件に対応した可視化機能

機能:
- ヒット率推移の可視化
- パラメータ差のヒートマップ
- 比較実験結果のチャート
"""

# 可視化ライブラリのインポート（オプション）
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np
    import seaborn as sns
    VISUALIZATION_AVAILABLE = True
except ImportError as e:
    print(f"可視化ライブラリが利用できません: {e}")
    print("matplotlib, numpy, seaborn をインストールしてください: pip install matplotlib numpy seaborn")
    VISUALIZATION_AVAILABLE = False
    # ダミークラスを定義
    class plt:
        @staticmethod
        def figure(*args, **kwargs): pass
        @staticmethod
        def savefig(*args, **kwargs): pass
        @staticmethod
        def close(*args, **kwargs): pass
    import math as np

from typing import List, Dict, Any, Tuple, Optional
import os
import datetime


class CluMPVisualizer:
    """
    CluMP結果の可視化クラス
    要件定義書準拠の可視化機能を提供
    """
    
    def __init__(self, output_dir: str = "visualization_output"):
        """
        可視化器を初期化
        
        Args:
            output_dir: 出力ディレクトリ
        """
        self.base_output_dir = output_dir
        self.visualization_enabled = VISUALIZATION_AVAILABLE
        
        # タイムスタンプ付きのサブフォルダを作成
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(output_dir, f"session_{timestamp}")
        self.output_dir = self.session_dir
        
        # 出力ディレクトリを作成
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            print(f"📁 可視化出力フォルダを作成しました: {self.output_dir}")
        
        if self.visualization_enabled:
            # フォント設定（英語表記用）
            plt.rcParams['font.family'] = ['DejaVu Sans', 'Arial', 'sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            
            # スタイル設定
            plt.style.use('seaborn-v0_8-darkgrid')
            self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        else:
            print("可視化ライブラリが利用できないため、テキストベースのレポートを生成します。")
    
    def plot_hit_rate_progression(self, trace: List[int], 
                                chunk_size: int = 16, cluster_size: int = 32,
                                cache_size: int = 4096, prefetch_window: int = 16,
                                window_size: int = 1000, save_path: Optional[str] = None) -> str:
        """
        ヒット率推移を可視化
        
        Args:
            trace: アクセストレース
            chunk_size: チャンクサイズ
            cluster_size: クラスタサイズ
            cache_size: キャッシュサイズ
            prefetch_window: プリフェッチ窓
            window_size: 移動平均の窓サイズ
            save_path: 保存パス（指定されなければ自動生成）
            
        Returns:
            str: 保存されたファイルパス
        """
        if not self.visualization_enabled:
            return self._generate_text_report("hit_rate_progression", {
                "chunk_size": chunk_size,
                "cluster_size": cluster_size,
                "trace_length": len(trace)
            })
        
        from clump_simulator import CluMPSimulator
        
        # シミュレータ初期化
        simulator = CluMPSimulator(chunk_size, cluster_size, cache_size, prefetch_window)
        
        # アクセス毎のヒット率を記録
        access_counts = []
        hit_rates = []
        
        for i, block_id in enumerate(trace):
            simulator.process_access(block_id)
            
            # 一定間隔でヒット率を記録
            if (i + 1) % 100 == 0:
                access_counts.append(i + 1)
                current_hit_rate = simulator.cache_hits / simulator.total_accesses
                hit_rates.append(current_hit_rate)
        
        # 移動平均計算
        if len(hit_rates) > window_size // 100:
            window = window_size // 100
            moving_avg = self._moving_average(hit_rates, window)
            moving_avg_x = access_counts[window-1:]
        else:
            moving_avg = hit_rates
            moving_avg_x = access_counts
        
        # プロット作成
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # ヒット率推移
        ax.plot(access_counts, hit_rates, alpha=0.3, color=self.colors[0], 
                label='Instantaneous Hit Rate', linewidth=1)
        ax.plot(moving_avg_x, moving_avg, color=self.colors[1], 
                label=f'Moving Average (window={window_size})', linewidth=2)
        
        # 最終ヒット率の水平線
        final_hit_rate = hit_rates[-1]
        ax.axhline(y=final_hit_rate, color=self.colors[2], linestyle='--', 
                  label=f'Final Hit Rate: {final_hit_rate:.3f}')
        
        # グラフ設定
        ax.set_xlabel('Number of Accesses', fontsize=12)
        ax.set_ylabel('Hit Rate', fontsize=12)
        ax.set_title(f'CluMP Hit Rate Progression\n'
                    f'(Chunk={chunk_size}, Cluster={cluster_size}, '
                    f'Cache={cache_size}, Prefetch Window={prefetch_window})', 
                    fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 1)
        
        # パラメータ情報を追加
        info_text = (f'Parameters:\n'
                    f'• Chunk Size: {chunk_size} blocks\n'
                    f'• Cluster Size: {cluster_size} chunks\n' 
                    f'• Cache Size: {cache_size} blocks\n'
                    f'• Prefetch Window: {prefetch_window} blocks')
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        
        # ファイル保存
        if save_path is None:
            save_path = os.path.join(self.output_dir, 
                                   f'hit_rate_progression_c{chunk_size}_cl{cluster_size}.png')
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return save_path
    
    def _moving_average(self, data: List[float], window: int) -> List[float]:
        """移動平均を計算"""
        if not VISUALIZATION_AVAILABLE:
            # numpy が利用できない場合の手動実装
            result = []
            for i in range(window - 1, len(data)):
                avg = sum(data[i - window + 1:i + 1]) / window
                result.append(avg)
            return result
        else:
            return list(np.convolve(data, np.ones(window)/window, mode='valid'))
    
    def _generate_text_report(self, report_type: str, data: Dict[str, Any]) -> str:
        """テキストベースのレポートを生成"""
        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_{timestamp}.txt"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"CluMP {report_type} レポート\n")
            f.write("=" * 50 + "\n")
            f.write(f"生成日時: {__import__('datetime').datetime.now()}\n\n")
            
            for key, value in data.items():
                f.write(f"{key}: {value}\n")
            
            f.write("\n注意: 可視化ライブラリが利用できないため、グラフは生成されませんでした。\n")
            f.write("matplotlib, numpy, seaborn をインストールして再実行してください。\n")
        
        return filepath
    
    def plot_parameter_heatmap(self, results: List[Dict[str, Any]], 
                             metric: str = 'hit_rate',
                             save_path: Optional[str] = None) -> str:
        """
        パラメータ差のヒートマップを作成
        
        Args:
            results: 実験結果のリスト
            metric: 可視化する評価指標
            save_path: 保存パス
            
        Returns:
            str: 保存されたファイルパス
        """
        if not self.visualization_enabled:
            return self._generate_parameter_text_report(results, metric)
        
        # パラメータの組み合わせを抽出
        chunk_sizes = sorted(list(set(r['chunk_size'] for r in results)))
        cluster_sizes = sorted(list(set(r['cluster_size'] for r in results)))
        
        # ヒートマップ用のマトリックス作成
        heatmap_data = [[0 for _ in chunk_sizes] for _ in cluster_sizes]
        
        for result in results:
            chunk_idx = chunk_sizes.index(result['chunk_size'])
            cluster_idx = cluster_sizes.index(result['cluster_size'])
            heatmap_data[cluster_idx][chunk_idx] = result[metric]
        
        # プロット作成
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # カラーマップ設定
        if metric == 'hit_rate':
            cmap = 'RdYlGn'
            vmin, vmax = 0, 1
        elif metric == 'prefetch_efficiency':
            cmap = 'Blues'
            vmin, vmax = 0, 1
        else:
            cmap = 'viridis'
            vmin, vmax = None, None
        
        # ヒートマップ描画
        heatmap_array = np.array(heatmap_data)
        im = ax.imshow(heatmap_array, cmap=cmap, aspect='auto', vmin=vmin, vmax=vmax)
        
        # 軸設定
        ax.set_xticks(range(len(chunk_sizes)))
        ax.set_yticks(range(len(cluster_sizes)))
        ax.set_xticklabels(chunk_sizes)
        ax.set_yticklabels(cluster_sizes)
        ax.set_xlabel('Chunk Size (blocks)', fontsize=12)
        ax.set_ylabel('Cluster Size (chunks)', fontsize=12)
        
        # タイトル設定
        metric_names = {
            'hit_rate': 'Hit Rate',
            'prefetch_efficiency': 'Prefetch Efficiency',
            'memory_usage_mc_rows': 'Memory Usage (MC Rows)'
        }
        title = f'Parameter {metric_names.get(metric, metric)} Heatmap'
        ax.set_title(title, fontsize=14, fontweight='bold')
        
        # 数値を各セルに表示
        for i in range(len(cluster_sizes)):
            for j in range(len(chunk_sizes)):
                value = heatmap_data[i][j]
                if metric in ['hit_rate', 'prefetch_efficiency']:
                    text = f'{value:.3f}'
                else:
                    text = f'{int(value)}'
                ax.text(j, i, text, ha='center', va='center', 
                       color='white' if value < (vmax or np.max(heatmap_array)) * 0.5 else 'black')
        
        # カラーバー
        cbar = plt.colorbar(im, ax=ax)
        if metric in ['hit_rate', 'prefetch_efficiency']:
            cbar.set_label(f'{metric_names.get(metric, metric)} (0-1)', fontsize=12)
        else:
            cbar.set_label(metric_names.get(metric, metric), fontsize=12)
        
        plt.tight_layout()
        
        # ファイル保存
        if save_path is None:
            save_path = os.path.join(self.output_dir, f'parameter_heatmap_{metric}.png')
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return save_path
    
    def _generate_parameter_text_report(self, results: List[Dict[str, Any]], metric: str) -> str:
        """パラメータ分析のテキストレポートを生成"""
        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"parameter_analysis_{metric}_{timestamp}.txt"
        filepath = os.path.join(self.output_dir, filename)
        
        # パラメータの組み合わせを抽出
        chunk_sizes = sorted(list(set(r['chunk_size'] for r in results)))
        cluster_sizes = sorted(list(set(r['cluster_size'] for r in results)))
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"CluMP パラメータ分析レポート - {metric}\n")
            f.write("=" * 60 + "\n")
            f.write(f"生成日時: {__import__('datetime').datetime.now()}\n\n")
            
            f.write("パラメータ別結果:\n")
            f.write("-" * 40 + "\n")
            
            # 表形式で出力
            f.write(f"{'チャンク\\クラスタ':<12}")
            for cluster_size in cluster_sizes:
                f.write(f"{cluster_size:>8}")
            f.write("\n")
            
            for chunk_size in chunk_sizes:
                f.write(f"{chunk_size:<12}")
                for cluster_size in cluster_sizes:
                    # 該当する結果を検索
                    value = None
                    for result in results:
                        if result['chunk_size'] == chunk_size and result['cluster_size'] == cluster_size:
                            value = result[metric]
                            break
                    
                    if value is not None:
                        if metric in ['hit_rate', 'prefetch_efficiency']:
                            f.write(f"{value:8.3f}")
                        else:
                            f.write(f"{int(value):8}")
                    else:
                        f.write(f"{'N/A':>8}")
                f.write("\n")
            
            # 最適パラメータを特定
            best_result = max(results, key=lambda x: x[metric])
            f.write(f"\n最適パラメータ:\n")
            f.write(f"  チャンクサイズ: {best_result['chunk_size']}\n")
            f.write(f"  クラスタサイズ: {best_result['cluster_size']}\n")
            f.write(f"  {metric}: {best_result[metric]}\n")
        
        return filepath
    
    def plot_baseline_comparison(self, comparison: Dict[str, Dict[str, Any]], 
                               save_path: Optional[str] = None) -> str:
        """
        ベースライン比較チャートを作成
        
        Args:
            comparison: 比較結果
            save_path: 保存パス
            
        Returns:
            str: 保存されたファイルパス
        """
        if not self.visualization_enabled:
            return self._generate_comparison_text_report(comparison)
        
        clump = comparison['clump']
        baseline = comparison['baseline']
        
        # 比較する指標
        metrics = ['hit_rate', 'prefetch_efficiency', 'prefetch_total', 'prefetch_used']
        metric_names = ['Hit Rate', 'Prefetch Efficiency', 'Prefetch Total', 'Prefetch Used']
        
        # データ準備
        clump_values = [clump[metric] for metric in metrics]
        baseline_values = [baseline[metric] for metric in metrics]
        
        # プロット作成
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
        axes = [ax1, ax2, ax3, ax4]
        
        for i, (ax, metric, name) in enumerate(zip(axes, metrics, metric_names)):
            methods = ['CluMP', 'Baseline']
            values = [clump_values[i], baseline_values[i]]
            colors = [self.colors[0], self.colors[1]]
            
            bars = ax.bar(methods, values, color=colors, alpha=0.8)
            
            # 数値ラベル追加
            for bar, value in zip(bars, values):
                height = bar.get_height()
                if metric in ['hit_rate', 'prefetch_efficiency']:
                    label = f'{value:.3f}'
                else:
                    label = f'{int(value):,}'
                ax.text(bar.get_x() + bar.get_width()/2., height + height*0.01,
                       label, ha='center', va='bottom', fontweight='bold')
            
            ax.set_title(name, fontsize=12, fontweight='bold')
            ax.set_ylabel('Value', fontsize=10)
            
            if metric in ['hit_rate', 'prefetch_efficiency']:
                ax.set_ylim(0, 1)
            else:
                ax.set_ylim(0, max(values) * 1.1)
            
            # 改善率計算と表示
            if baseline_values[i] > 0:
                improvement = ((clump_values[i] - baseline_values[i]) / baseline_values[i]) * 100
                improvement_text = f'Improvement: {improvement:+.1f}%'
                ax.text(0.5, 0.95, improvement_text, transform=ax.transAxes, 
                       ha='center', va='top', fontsize=10, 
                       bbox=dict(boxstyle='round', facecolor='lightgreen' if improvement > 0 else 'lightcoral', alpha=0.7))
        
        plt.suptitle('CluMP vs Baseline Comparison', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        # ファイル保存
        if save_path is None:
            save_path = os.path.join(self.output_dir, 'baseline_comparison.png')
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return save_path
    
    def _generate_comparison_text_report(self, comparison: Dict[str, Dict[str, Any]]) -> str:
        """ベースライン比較のテキストレポートを生成"""
        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"baseline_comparison_{timestamp}.txt"
        filepath = os.path.join(self.output_dir, filename)
        
        clump = comparison['clump']
        baseline = comparison['baseline']
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("CluMP vs ベースライン比較レポート\n")
            f.write("=" * 50 + "\n")
            f.write(f"生成日時: {__import__('datetime').datetime.now()}\n\n")
            
            metrics = [
                ('hit_rate', 'ヒット率'),
                ('prefetch_efficiency', 'プリフェッチ効率'),
                ('prefetch_total', 'プリフェッチ総数'),
                ('prefetch_used', 'プリフェッチ使用数'),
                ('memory_usage_mc_rows', 'メモリ使用量 (MC行数)')
            ]
            
            for metric, name in metrics:
                if metric in clump and metric in baseline:
                    clump_val = clump[metric]
                    baseline_val = baseline[metric]
                    
                    f.write(f"{name}:\n")
                    if isinstance(clump_val, float):
                        f.write(f"  CluMP:      {clump_val:.3f}\n")
                    else:
                        f.write(f"  CluMP:      {clump_val}\n")
                    
                    if isinstance(baseline_val, float):
                        f.write(f"  ベースライン: {baseline_val:.3f}\n")
                    else:
                        f.write(f"  ベースライン: {baseline_val}\n")
                    
                    if baseline_val > 0:
                        improvement = ((clump_val - baseline_val) / baseline_val) * 100
                        f.write(f"  改善率:     {improvement:+.1f}%\n")
                    f.write("\n")
        
        return filepath
    
    def create_visualization_report(self, results: List[Dict[str, Any]], 
                                  analysis: Dict[str, Any],
                                  comparison: Dict[str, Dict[str, Any]],
                                  trace: List[int]) -> List[str]:
        """
        包括的な可視化レポートを生成
        
        各種類のグラフごとにサブフォルダを作成し、整理された形で出力します。
        
        フォルダ構造:
        visualization_output/
        └── session_YYYYMMDD_HHMMSS/
            ├── hit_rate_progression/
            ├── parameter_heatmaps/
            ├── baseline_comparison/
            └── summary_report.txt
        
        Args:
            results: パラメータ実験結果
            analysis: 分析結果
            comparison: ベースライン比較結果
            trace: アクセストレース
            
        Returns:
            List[str]: 生成されたファイルパスのリスト
        """
        generated_files = []
        
        print("📊 可視化レポート生成中...")
        print(f"出力先: {self.output_dir}")
        
        # サブフォルダを作成
        subfolders = {
            'hit_rate_progression': 'ヒット率推移',
            'parameter_heatmaps': 'パラメータヒートマップ',
            'baseline_comparison': 'ベースライン比較'
        }
        
        for folder_name, description in subfolders.items():
            folder_path = os.path.join(self.output_dir, folder_name)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                print(f"  📁 {description}フォルダ作成: {folder_name}/")
        
        # 1. ヒット率推移
        print("  1. ヒット率推移チャート生成中...")
        best_params = analysis['best_parameters']
        hit_rate_path = self.plot_hit_rate_progression(
            trace, 
            chunk_size=best_params['chunk_size'],
            cluster_size=best_params['cluster_size'],
            save_path=os.path.join(self.output_dir, 'hit_rate_progression', 
                                 f'hit_rate_progression_best_params.png')
        )
        generated_files.append(hit_rate_path)
        
        # 2. パラメータヒートマップ（複数指標）
        metrics_info = {
            'hit_rate': 'ヒット率',
            'prefetch_efficiency': 'プリフェッチ効率', 
            'memory_usage_mc_rows': 'メモリ使用量'
        }
        
        for metric, description in metrics_info.items():
            print(f"  2. {description}ヒートマップ生成中...")
            heatmap_path = self.plot_parameter_heatmap(
                results, 
                metric,
                save_path=os.path.join(self.output_dir, 'parameter_heatmaps',
                                     f'heatmap_{metric}.png')
            )
            generated_files.append(heatmap_path)
        
        # 3. ベースライン比較
        if comparison:
            print("  3. ベースライン比較チャート生成中...")
            comparison_path = self.plot_baseline_comparison(
                comparison,
                save_path=os.path.join(self.output_dir, 'baseline_comparison',
                                     'clump_vs_baseline.png')
            )
            generated_files.append(comparison_path)
        else:
            print("  3. ベースライン比較データなし - スキップ")
        
        # 4. サマリーレポート作成
        print("  4. サマリーレポート生成中...")
        summary_path = self._create_summary_report(results, analysis, comparison)
        generated_files.append(summary_path)
        
        print(f"✅ 可視化レポート生成完了！")
        print(f"📁 出力ディレクトリ: {self.output_dir}")
        print(f"📄 生成ファイル数: {len(generated_files)}")
        print(f"\n📋 生成されたファイル:")
        for i, path in enumerate(generated_files, 1):
            relative_path = os.path.relpath(path, self.base_output_dir)
            print(f"  {i}. {relative_path}")
        
        return generated_files
    
    def _create_summary_report(self, results: List[Dict[str, Any]], 
                             analysis: Dict[str, Any],
                             comparison: Optional[Dict[str, Dict[str, Any]]]) -> str:
        """
        可視化レポートのサマリーファイルを作成
        
        Args:
            results: パラメータ実験結果
            analysis: 分析結果  
            comparison: ベースライン比較結果
            
        Returns:
            str: サマリーファイルのパス
        """
        summary_path = os.path.join(self.output_dir, 'summary_report.txt')
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            # ヘッダー
            timestamp = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
            f.write("=" * 80 + "\n")
            f.write("CluMP 可視化レポート サマリー\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成日時: {timestamp}\n")
            f.write(f"出力ディレクトリ: {self.output_dir}\n\n")
            
            # 実験概要
            f.write("📊 実験概要\n")
            f.write("-" * 40 + "\n")
            f.write(f"パラメータ組み合わせ数: {len(results)}\n")
            
            chunk_sizes = sorted(list(set(r['chunk_size'] for r in results)))
            cluster_sizes = sorted(list(set(r['cluster_size'] for r in results)))
            f.write(f"テストしたチャンクサイズ: {chunk_sizes}\n")
            f.write(f"テストしたクラスタサイズ: {cluster_sizes}\n\n")
            
            # 最適パラメータ
            if 'best_parameters' in analysis:
                best = analysis['best_parameters']
                f.write("🏆 最適パラメータ\n")
                f.write("-" * 40 + "\n")
                f.write(f"チャンクサイズ: {best['chunk_size']} ブロック\n")
                f.write(f"クラスタサイズ: {best['cluster_size']} チャンク\n")
                f.write(f"ヒット率: {best['hit_rate']:.3f} ({best['hit_rate']*100:.1f}%)\n")
                f.write(f"プリフェッチ効率: {best['prefetch_efficiency']:.3f} ({best['prefetch_efficiency']*100:.1f}%)\n")
                f.write(f"MC行数: {best['mc_rows']:,}\n\n")
            
            # ベースライン比較
            if comparison and 'clump' in comparison and 'baseline' in comparison:
                clump_hit = comparison['clump']['hit_rate']
                baseline_hit = comparison['baseline']['hit_rate']
                if baseline_hit > 0:
                    improvement = (clump_hit - baseline_hit) / baseline_hit * 100
                    f.write("📈 ベースライン比較\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"CluMP ヒット率: {clump_hit:.3f} ({clump_hit*100:.1f}%)\n")
                    f.write(f"ベースライン ヒット率: {baseline_hit:.3f} ({baseline_hit*100:.1f}%)\n")
                    f.write(f"改善率: {improvement:+.1f}%\n\n")
            
            # 生成されたファイル
            f.write("📄 生成されたファイル\n")
            f.write("-" * 40 + "\n")
            f.write("hit_rate_progression/\n")
            f.write("  - hit_rate_progression_best_params.png : 最適パラメータでのヒット率推移\n\n")
            
            f.write("parameter_heatmaps/\n")
            f.write("  - heatmap_hit_rate.png : ヒット率ヒートマップ\n")
            f.write("  - heatmap_prefetch_efficiency.png : プリフェッチ効率ヒートマップ\n") 
            f.write("  - heatmap_memory_usage_mc_rows.png : メモリ使用量ヒートマップ\n\n")
            
            if comparison:
                f.write("baseline_comparison/\n")
                f.write("  - clump_vs_baseline.png : CluMP vs ベースライン比較\n\n")
            
            # 使用方法
            f.write("💡 ファイルの見方\n")
            f.write("-" * 40 + "\n")
            f.write("1. ヒット率推移: 学習効果と収束の様子を確認\n")
            f.write("2. ヒートマップ: パラメータ間の性能差を色で可視化\n")
            f.write("3. ベースライン比較: CluMPの有効性を定量評価\n")
            f.write("4. 暖色系(赤): 高性能、寒色系(青): 低性能\n\n")
            
            f.write("=" * 80 + "\n")
        
        return summary_path


def create_visualization_demo():
    """
    可視化のデモンストレーション
    
    新しいフォルダ構造での可視化機能をテストします。
    """
    from clump_simulator import TraceGenerator
    import random
    
    # デモ用の設定
    random.seed(42)
    visualizer = CluMPVisualizer(output_dir="demo_visualization")
    
    print("📊 可視化デモ実行中...")
    print(f"可視化機能利用可能: {VISUALIZATION_AVAILABLE}")
    print(f"出力ディレクトリ: {visualizer.output_dir}")
    
    # 小規模トレース生成
    trace = TraceGenerator.generate_synthetic_trace(
        n_events=2000,  # 規模を小さくしてテスト
        num_files=20,
        avg_file_length_blocks=50,
        sequential_prob=0.6,
        jump_prob=0.1
    )
    
    # ヒット率推移の例（デモ用サブフォルダに保存）
    print("1. ヒット率推移チャート生成...")
    demo_subfolder = os.path.join(visualizer.output_dir, "demo_charts")
    if not os.path.exists(demo_subfolder):
        os.makedirs(demo_subfolder)
    
    hit_rate_path = visualizer.plot_hit_rate_progression(
        trace,
        save_path=os.path.join(demo_subfolder, "demo_hit_rate_progression.png")
    )
    print(f"   → {os.path.relpath(hit_rate_path)}")
    
    print("✅ 可視化デモ完了！")
    print(f"📁 出力先を確認してください: {visualizer.output_dir}")


if __name__ == "__main__":
    create_visualization_demo()