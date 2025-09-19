#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CluMP Interactive Parameter Configuration and Testing Tool
CluMPインタラクティブパラメータ設定とテストツール

CluMPアルゴリズムの理解と検証に重要なパラメータをカスタマイズし、
その効果をリアルタイムで確認できるツール。

主要機能:
1. パラメータ設定プリセット
2. インタラクティブパラメータ調整
3. コマンドライン引数による設定
4. パフォーマンス予測とアドバイス
5. 設定検証と最適化提案

作成者: GitHub Copilot
更新日: 2025年9月19日
"""

import sys
import os
import argparse
import json
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, asdict

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from clump_simulator import *


@dataclass
class CluMPConfiguration:
    """CluMPシミュレータの設定パラメータクラス"""
    # 基本アルゴリズムパラメータ
    chunk_size_blocks: int = 16          # チャンクサイズ（ブロック数）
    cluster_size_chunks: int = 64        # クラスタサイズ（チャンク数）
    cache_size_blocks: int = 4096        # キャッシュサイズ（ブロック数）
    prefetch_window_blocks: int = 16     # プリフェッチ窓サイズ（ブロック数）
    
    # ワークロード設定
    workload_type: str = "kvm"           # ワークロード種類（kvm, kernel, mixed, custom）
    workload_size: int = 15000           # ワークロードサイズ（ブロック数）
    workload_range: int = 30000          # ブロック範囲
    
    # 実験設定
    enable_comparison: bool = True        # Linux先読みとの比較を実行
    enable_visualization: bool = True     # 結果の可視化を実行
    random_seed: int = 42                # 乱数シード
    
    # 詳細設定
    verbose: bool = False                # 詳細ログ出力
    output_dir: str = "./results"        # 結果出力ディレクトリ


class ParameterPresets:
    """パラメータプリセット定義"""
    
    @staticmethod
    def get_presets() -> Dict[str, CluMPConfiguration]:
        """利用可能なプリセット一覧を取得"""
        return {
            "paper_compliant": CluMPConfiguration(
                chunk_size_blocks=16,
                cluster_size_chunks=64,
                cache_size_blocks=4096,
                prefetch_window_blocks=16,
                workload_type="kvm",
                workload_size=15000,
                workload_range=30000
            ),
            "high_performance": CluMPConfiguration(
                chunk_size_blocks=8,
                cluster_size_chunks=128,
                cache_size_blocks=8192,
                prefetch_window_blocks=32,
                workload_type="kernel",
                workload_size=25000,
                workload_range=50000
            ),
            "memory_efficient": CluMPConfiguration(
                chunk_size_blocks=32,
                cluster_size_chunks=32,
                cache_size_blocks=2048,
                prefetch_window_blocks=8,
                workload_type="mixed",
                workload_size=10000,
                workload_range=20000
            ),
            "small_scale": CluMPConfiguration(
                chunk_size_blocks=4,
                cluster_size_chunks=16,
                cache_size_blocks=1024,
                prefetch_window_blocks=4,
                workload_type="kvm",
                workload_size=5000,
                workload_range=10000
            ),
            "large_scale": CluMPConfiguration(
                chunk_size_blocks=64,
                cluster_size_chunks=256,
                cache_size_blocks=16384,
                prefetch_window_blocks=64,
                workload_type="kernel",
                workload_size=50000,
                workload_range=100000
            )
        }
    
    @staticmethod
    def describe_preset(preset_name: str) -> str:
        """プリセットの説明を取得"""
        descriptions = {
            "paper_compliant": "論文準拠設定 - 論文の実験条件を再現",
            "high_performance": "高性能設定 - 最大のヒット率向上を目指す",
            "memory_efficient": "メモリ効率設定 - メモリ使用量を最小化",
            "small_scale": "小規模設定 - 軽量テストや学習用",
            "large_scale": "大規模設定 - 大容量ワークロード対応"
        }
        return descriptions.get(preset_name, "説明なし")


class ParameterValidator:
    """パラメータ検証クラス"""
    
    @staticmethod
    def validate_configuration(config: CluMPConfiguration) -> Tuple[bool, List[str]]:
        """設定の妥当性を検証"""
        errors = []
        warnings = []
        
        # 基本的な範囲チェック
        if config.chunk_size_blocks <= 0:
            errors.append("チャンクサイズは正の値である必要があります")
        elif config.chunk_size_blocks > 1024:
            warnings.append("チャンクサイズが大きすぎます（推奨: 4-64）")
        
        if config.cluster_size_chunks <= 0:
            errors.append("クラスタサイズは正の値である必要があります")
        elif config.cluster_size_chunks > 512:
            warnings.append("クラスタサイズが大きすぎます（推奨: 16-256）")
        
        if config.cache_size_blocks <= 0:
            errors.append("キャッシュサイズは正の値である必要があります")
        elif config.cache_size_blocks < 1024:
            warnings.append("キャッシュサイズが小さすぎます（推奨: 1024以上）")
        
        if config.prefetch_window_blocks <= 0:
            errors.append("プリフェッチ窓サイズは正の値である必要があります")
        elif config.prefetch_window_blocks > config.chunk_size_blocks:
            warnings.append("プリフェッチ窓がチャンクサイズより大きいです")
        
        # メモリ使用量予測
        estimated_memory_mb = ParameterValidator.estimate_memory_usage(config)
        if estimated_memory_mb > 1000:
            warnings.append(f"予想メモリ使用量が大きいです: {estimated_memory_mb:.1f}MB")
        
        # パフォーマンス最適性チェック
        if config.chunk_size_blocks > config.prefetch_window_blocks * 4:
            warnings.append("チャンクサイズがプリフェッチ窓に対して大きすぎる可能性があります")
        
        # ワークロード設定チェック
        if config.workload_size <= 0:
            errors.append("ワークロードサイズは正の値である必要があります")
        
        if config.workload_type not in ["kvm", "kernel", "mixed", "custom"]:
            errors.append("無効なワークロード種類です")
        
        return len(errors) == 0, errors + warnings
    
    @staticmethod
    def estimate_memory_usage(config: CluMPConfiguration) -> float:
        """メモリ使用量を推定（MB）"""
        # キャッシュメモリ（ブロックあたり8B想定）
        cache_memory = config.cache_size_blocks * 8
        
        # MC行のメモリ（最大使用想定）
        max_chunks = config.workload_range // config.chunk_size_blocks
        max_mc_rows = min(max_chunks, config.workload_size // 10)  # 10%がアクティブと想定
        mc_memory = max_mc_rows * 24  # 24B per MC row
        
        total_bytes = cache_memory + mc_memory
        return total_bytes / (1024 * 1024)  # MB換算
    
    @staticmethod
    def suggest_optimizations(config: CluMPConfiguration) -> List[str]:
        """最適化提案を生成"""
        suggestions = []
        
        # チャンクサイズの最適化
        if config.chunk_size_blocks < 8:
            suggestions.append("チャンクサイズを8-16に増やすと効率が向上する可能性があります")
        elif config.chunk_size_blocks > 32:
            suggestions.append("チャンクサイズを16-32に減らすと応答性が向上する可能性があります")
        
        # クラスタサイズの最適化
        if config.cluster_size_chunks < 32:
            suggestions.append("クラスタサイズを64-128に増やすとMC効率が向上する可能性があります")
        
        # プリフェッチ窓の最適化
        optimal_window = config.chunk_size_blocks * 2
        if config.prefetch_window_blocks < optimal_window // 2:
            suggestions.append(f"プリフェッチ窓を{optimal_window}程度に増やすと効果的です")
        
        return suggestions


class InteractiveConfigurationInterface:
    """インタラクティブ設定インターフェース"""
    
    def __init__(self):
        self.config = CluMPConfiguration()
        self.presets = ParameterPresets.get_presets()
    
    def run_interactive_setup(self) -> CluMPConfiguration:
        """インタラクティブ設定を実行"""
        print("🔧 CluMPパラメータ設定ツール")
        print("=" * 50)
        
        # プリセット選択
        if self._ask_yes_no("プリセット設定を使用しますか？"):
            preset_name = self._select_preset()
            if preset_name:
                self.config = self.presets[preset_name]
                print(f"✅ プリセット '{preset_name}' を適用しました")
        
        # カスタム設定
        if self._ask_yes_no("パラメータをカスタマイズしますか？"):
            self._customize_parameters()
        
        # 設定検証
        self._validate_and_suggest()
        
        return self.config
    
    def _select_preset(self) -> Optional[str]:
        """プリセット選択UI"""
        print("\n📋 利用可能なプリセット:")
        preset_names = list(self.presets.keys())
        
        for i, name in enumerate(preset_names, 1):
            description = ParameterPresets.describe_preset(name)
            print(f"  {i}. {name} - {description}")
        
        try:
            choice = input(f"\n選択してください (1-{len(preset_names)}, Enter でスキップ): ").strip()
            if not choice:
                return None
            
            index = int(choice) - 1
            if 0 <= index < len(preset_names):
                return preset_names[index]
            else:
                print("❌ 無効な選択です")
                return None
        except ValueError:
            print("❌ 数値を入力してください")
            return None
    
    def _customize_parameters(self):
        """パラメータカスタマイズUI"""
        print("\n🔧 パラメータカスタマイズ")
        print("-" * 30)
        
        # 基本パラメータ
        print("\n💡 基本アルゴリズムパラメータ:")
        self.config.chunk_size_blocks = self._get_int_input(
            "チャンクサイズ（ブロック数）", 
            self.config.chunk_size_blocks, 
            1, 1024,
            "ディスクブロックをまとめる単位。小さいほど細かい制御、大きいほど効率的"
        )
        
        self.config.cluster_size_chunks = self._get_int_input(
            "クラスタサイズ（チャンク数）", 
            self.config.cluster_size_chunks, 
            1, 512,
            "MCテーブルの分割単位。大きいほどメモリ効率向上"
        )
        
        self.config.cache_size_blocks = self._get_int_input(
            "キャッシュサイズ（ブロック数）", 
            self.config.cache_size_blocks, 
            256, 65536,
            "メモリキャッシュの容量。大きいほどヒット率向上"
        )
        
        self.config.prefetch_window_blocks = self._get_int_input(
            "プリフェッチ窓サイズ（ブロック数）", 
            self.config.prefetch_window_blocks, 
            1, 256,
            "一度にプリフェッチするブロック数。チャンクサイズとのバランスが重要"
        )
        
        # ワークロード設定
        print("\n🏗️ ワークロード設定:")
        workload_choices = ["kvm", "kernel", "mixed", "custom"]
        workload_descriptions = [
            "VM起動パターン（高い逐次性）",
            "カーネルビルドパターン（混合アクセス）", 
            "混合パターン（逐次とランダムの組み合わせ）",
            "カスタムパターン"
        ]
        
        print("ワークロード種類:")
        for i, (choice, desc) in enumerate(zip(workload_choices, workload_descriptions), 1):
            print(f"  {i}. {choice} - {desc}")
        
        workload_index = self._get_int_input("選択", 1, 1, len(workload_choices)) - 1
        self.config.workload_type = workload_choices[workload_index]
        
        self.config.workload_size = self._get_int_input(
            "ワークロードサイズ（ブロック数）", 
            self.config.workload_size, 
            1000, 1000000,
            "シミュレーションするI/O要求数"
        )
        
        # 実験設定
        print("\n⚙️ 実験設定:")
        self.config.enable_comparison = self._ask_yes_no("Linux先読みとの比較を実行する")
        self.config.enable_visualization = self._ask_yes_no("結果の可視化を実行する")
        self.config.verbose = self._ask_yes_no("詳細ログを出力する")
    
    def _validate_and_suggest(self):
        """設定の検証と提案"""
        print("\n🔍 設定検証中...")
        
        is_valid, messages = ParameterValidator.validate_configuration(self.config)
        
        if not is_valid:
            print("❌ 設定にエラーがあります:")
            for msg in messages:
                print(f"  • {msg}")
            return
        
        # 警告表示
        warnings = [msg for msg in messages if "警告" in msg or "推奨" in msg or "可能性" in msg]
        if warnings:
            print("⚠️ 警告:")
            for warning in warnings:
                print(f"  • {warning}")
        
        # 最適化提案
        suggestions = ParameterValidator.suggest_optimizations(self.config)
        if suggestions:
            print("\n💡 最適化提案:")
            for suggestion in suggestions:
                print(f"  • {suggestion}")
        
        # メモリ使用量予測
        memory_mb = ParameterValidator.estimate_memory_usage(self.config)
        print(f"\n📊 予想メモリ使用量: {memory_mb:.1f} MB")
        
        print("✅ 設定検証完了")
    
    def _get_int_input(self, prompt: str, default: int, min_val: int, max_val: int, help_text: str = "") -> int:
        """整数入力を取得"""
        while True:
            if help_text:
                print(f"  💡 {help_text}")
            
            user_input = input(f"{prompt} (現在: {default}, 範囲: {min_val}-{max_val}): ").strip()
            
            if not user_input:
                return default
            
            try:
                value = int(user_input)
                if min_val <= value <= max_val:
                    return value
                else:
                    print(f"❌ 値は {min_val} から {max_val} の範囲で入力してください")
            except ValueError:
                print("❌ 整数を入力してください")
    
    def _ask_yes_no(self, question: str, default: bool = True) -> bool:
        """Yes/No質問"""
        default_text = "Y/n" if default else "y/N"
        response = input(f"{question} ({default_text}): ").strip().lower()
        
        if not response:
            return default
        
        return response in ['y', 'yes', 'はい', 'h']


class CluMPParameterTester:
    """CluMPパラメータテスター"""
    
    def __init__(self, config: CluMPConfiguration):
        self.config = config
    
    def run_test(self) -> Dict[str, Any]:
        """テスト実行"""
        print(f"\n🚀 CluMPシミュレーション実行中...")
        print(f"設定: chunk={self.config.chunk_size_blocks}, cluster={self.config.cluster_size_chunks}")
        print(f"     cache={self.config.cache_size_blocks}, window={self.config.prefetch_window_blocks}")
        
        # 乱数シード設定
        random.seed(self.config.random_seed)
        
        # ワークロード生成
        trace = self._generate_workload()
        
        # CluMP実験
        clump_params = {
            "chunk_size": self.config.chunk_size_blocks,
            "cluster_size": self.config.cluster_size_chunks,
            "prefetch_window": self.config.prefetch_window_blocks
        }
        
        results = compare_clump_vs_readahead(trace, clump_params, self.config.cache_size_blocks)
        
        # 結果表示
        self._display_results(results)
        
        # 可視化
        if self.config.enable_visualization:
            self._generate_visualizations(results, trace)
        
        return results
    
    def _generate_workload(self) -> List[int]:
        """ワークロード生成"""
        if self.config.workload_type == "kvm":
            return WorkloadGenerator.generate_kvm_workload(
                self.config.workload_size, 
                self.config.workload_range
            )
        elif self.config.workload_type == "kernel":
            return WorkloadGenerator.generate_kernel_build_workload(
                self.config.workload_size
            )
        elif self.config.workload_type == "mixed":
            # 混合ワークロード（50% KVM, 50% Kernel）
            kvm_trace = WorkloadGenerator.generate_kvm_workload(
                self.config.workload_size // 2, 
                self.config.workload_range
            )
            kernel_trace = WorkloadGenerator.generate_kernel_build_workload(
                self.config.workload_size // 2
            )
            return kvm_trace + kernel_trace
        else:  # custom
            return self._generate_custom_workload()
    
    def _generate_custom_workload(self) -> List[int]:
        """カスタムワークロード生成"""
        trace = []
        current_block = 0
        
        for _ in range(self.config.workload_size):
            pattern = random.random()
            
            if pattern < 0.6:  # 60% 逐次
                trace.append(current_block)
                current_block += 1
            elif pattern < 0.8:  # 20% 小ジャンプ
                current_block += random.randint(1, 50)
                trace.append(current_block)
            else:  # 20% 大ジャンプ
                current_block = random.randint(0, self.config.workload_range)
                trace.append(current_block)
        
        return trace
    
    def _display_results(self, results: Dict[str, Any]):
        """結果表示"""
        print("\n📊 実験結果")
        print("=" * 40)
        
        clump = results["clump"]
        readahead = results["readahead"]
        improvement = results["improvement"]
        
        print(f"Linux先読み:")
        print(f"  ヒット率: {readahead['hit_rate']:.3f}")
        print(f"  プリフェッチ効率: {readahead['prefetch_efficiency']:.3f}")
        
        print(f"\nCluMP:")
        print(f"  ヒット率: {clump['hit_rate']:.3f}")
        print(f"  プリフェッチ効率: {clump['prefetch_efficiency']:.3f}")
        print(f"  MC行数: {clump['memory_usage_mc_rows']}")
        memory_mb = clump.get('memory_usage_kb', 0) / 1024
        print(f"  メモリ使用量: {memory_mb:.1f} MB")
        
        print(f"\n🎯 比較結果:")
        print(f"  ヒット率改善: {improvement['hit_rate_improvement']:.2f}x")
        print(f"  ヒット率差分: {improvement['hit_rate_difference']:+.3f}")
        
        # パフォーマンス評価
        if improvement['hit_rate_improvement'] > 1.1:
            print("✅ 優秀な結果です！CluMPが明確に優位性を示しています")
        elif improvement['hit_rate_improvement'] > 1.0:
            print("✅ 良好な結果です。CluMPが若干の改善を達成しています")
        else:
            print("⚠️ Linux先読みの方が良好です。パラメータ調整を検討してください")
    
    def _generate_visualizations(self, results: Dict[str, Any], trace: List[int]):
        """可視化生成"""
        try:
            from visualization import PaperBasedVisualizer
            
            print("\n🎨 可視化生成中...")
            visualizer = PaperBasedVisualizer()
            session_dir = visualizer.create_session_directory()
            
            # ベースライン比較
            visualizer.plot_baseline_comparison(results["clump"], results["readahead"])
            
            # ヒット率推移（サンプルサイズを制限）
            sample_trace = trace[:min(5000, len(trace))]
            visualizer.plot_hit_rate_progression(
                sample_trace,
                chunk_size=self.config.chunk_size_blocks,
                cluster_size=self.config.cluster_size_chunks
            )
            
            print(f"✅ 可視化完了: {session_dir}")
            
        except ImportError:
            print("⚠️ 可視化ライブラリが見つかりません")
        except Exception as e:
            print(f"❌ 可視化エラー: {e}")


def setup_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを設定"""
    parser = argparse.ArgumentParser(
        description="CluMPパラメータ設定・テストツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # インタラクティブモード
  python clump_config_tool.py
  
  # プリセット使用
  python clump_config_tool.py --preset paper_compliant
  
  # カスタムパラメータ
  python clump_config_tool.py --chunk-size 16 --cluster-size 128 --cache-size 8192
  
  # 設定ファイルから読み込み
  python clump_config_tool.py --config config.json
  
  # 設定保存
  python clump_config_tool.py --preset high_performance --save-config my_config.json
        """
    )
    
    # 実行モード
    parser.add_argument("--interactive", "-i", action="store_true", 
                       help="インタラクティブモードで実行")
    parser.add_argument("--preset", "-p", choices=list(ParameterPresets.get_presets().keys()),
                       help="プリセット設定を使用")
    
    # パラメータ設定
    parser.add_argument("--chunk-size", type=int, metavar="N",
                       help="チャンクサイズ（ブロック数）")
    parser.add_argument("--cluster-size", type=int, metavar="N", 
                       help="クラスタサイズ（チャンク数）")
    parser.add_argument("--cache-size", type=int, metavar="N",
                       help="キャッシュサイズ（ブロック数）")
    parser.add_argument("--prefetch-window", type=int, metavar="N",
                       help="プリフェッチ窓サイズ（ブロック数）")
    
    # ワークロード設定
    parser.add_argument("--workload", choices=["kvm", "kernel", "mixed", "custom"],
                       help="ワークロード種類")
    parser.add_argument("--workload-size", type=int, metavar="N",
                       help="ワークロードサイズ（ブロック数）")
    parser.add_argument("--workload-range", type=int, metavar="N",
                       help="ブロック範囲")
    
    # 実験制御
    parser.add_argument("--no-comparison", action="store_true",
                       help="Linux先読みとの比較をスキップ")
    parser.add_argument("--no-visualization", action="store_true",
                       help="可視化をスキップ")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="詳細ログを出力")
    parser.add_argument("--seed", type=int, default=42,
                       help="乱数シード")
    
    # 設定ファイル
    parser.add_argument("--config", metavar="FILE",
                       help="設定ファイルから読み込み")
    parser.add_argument("--save-config", metavar="FILE",
                       help="設定をファイルに保存")
    
    # その他
    parser.add_argument("--list-presets", action="store_true",
                       help="利用可能なプリセット一覧を表示")
    parser.add_argument("--validate-only", action="store_true",
                       help="設定検証のみ実行（テストはスキップ）")
    
    return parser


def main():
    """メイン関数"""
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    # プリセット一覧表示
    if args.list_presets:
        print("📋 利用可能なプリセット:")
        for name, preset in ParameterPresets.get_presets().items():
            description = ParameterPresets.describe_preset(name)
            print(f"  {name}: {description}")
        return
    
    # 設定読み込み
    config = CluMPConfiguration()
    
    # 設定ファイルから読み込み
    if args.config:
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
                config = CluMPConfiguration(**config_dict)
            print(f"✅ 設定ファイル '{args.config}' から読み込みました")
        except Exception as e:
            print(f"❌ 設定ファイル読み込みエラー: {e}")
            return
    
    # プリセット適用
    elif args.preset:
        presets = ParameterPresets.get_presets()
        config = presets[args.preset]
        print(f"✅ プリセット '{args.preset}' を適用しました")
    
    # インタラクティブモード
    elif args.interactive or len(sys.argv) == 1:
        interface = InteractiveConfigurationInterface()
        config = interface.run_interactive_setup()
    
    # コマンドライン引数から設定
    if args.chunk_size is not None:
        config.chunk_size_blocks = args.chunk_size
    if args.cluster_size is not None:
        config.cluster_size_chunks = args.cluster_size
    if args.cache_size is not None:
        config.cache_size_blocks = args.cache_size
    if args.prefetch_window is not None:
        config.prefetch_window_blocks = args.prefetch_window
    if args.workload is not None:
        config.workload_type = args.workload
    if args.workload_size is not None:
        config.workload_size = args.workload_size
    if args.workload_range is not None:
        config.workload_range = args.workload_range
    
    config.enable_comparison = not args.no_comparison
    config.enable_visualization = not args.no_visualization
    config.verbose = args.verbose
    config.random_seed = args.seed
    
    # 設定検証
    is_valid, messages = ParameterValidator.validate_configuration(config)
    if not is_valid:
        print("❌ 設定にエラーがあります:")
        for msg in messages:
            print(f"  • {msg}")
        return
    
    # 設定保存
    if args.save_config:
        try:
            with open(args.save_config, 'w', encoding='utf-8') as f:
                json.dump(asdict(config), f, indent=2, ensure_ascii=False)
            print(f"✅ 設定を '{args.save_config}' に保存しました")
        except Exception as e:
            print(f"❌ 設定保存エラー: {e}")
    
    # 検証のみモード
    if args.validate_only:
        print("✅ 設定検証完了")
        return
    
    # テスト実行
    tester = CluMPParameterTester(config)
    results = tester.run_test()
    
    print("\n🎯 実験完了!")


if __name__ == "__main__":
    main()