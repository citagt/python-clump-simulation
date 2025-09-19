# CluMP Simulator

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Status](https://img.shields.io/badge/Status-Ready-green)

## 📖 概要

CluMP (CLUstered Markov-chain Prefetching) 論文に基づくストレージI/Oプリフェッチシミュレータ。

**論文**: "CluMP: Clustered Markov Chain for Storage I/O Prefetch" by Sungmin Jung, Hyeonmyeong Lee, Heeseung Jo

## 🚀 特徴

- **論文準拠実装**: Section 3.2-3.3の完全実装
- **インタラクティブ設定**: 5種類のプリセット + カスタム調整
- **性能比較**: Linux ReadAheadとの比較
- **可視化機能**: ヒートマップ、推移グラフ、HTMLレポート

##  インストール

```bash
git clone <repository-url>
cd python-clump-simulator

# 可視化機能を使う場合
pip install matplotlib numpy seaborn
```

## ⚡ クイックスタート

### 🎯 インタラクティブ設定（推奨）

```bash
# ガイド付き設定
python clump_config_tool.py

# プリセットを使用
python clump_config_tool.py --preset paper_compliant    # 論文準拠
python clump_config_tool.py --preset high_performance   # 高性能
python clump_config_tool.py --preset memory_efficient   # メモリ効率
```

### 🔍 基本実行

```bash
# 論文準拠アルゴリズム
python clump_simulator.py

# 包括的性能評価（パラメータ最適化）
python performance_evaluation.py

# 可視化レポート生成
python visualization.py
```

## 📊 主要パラメータ

| パラメータ | 推奨値 | 効果 |
|-----------|--------|------|
| **チャンクサイズ** | 8-32 | 小さい→細かい制御、大きい→効率向上 |
| **クラスタサイズ** | 32-128 | 大きい→メモリ効率向上 |
| **キャッシュサイズ** | 2048-8192 | 大きい→ヒット率向上 |
| **プリフェッチ窓** | チャンクサイズの1-4倍 | バランス調整が重要 |

## 📈 評価指標

- **ヒット率**: キャッシュにデータが存在した割合（目標: 60%以上）
- **プリフェッチ効率**: プリフェッチが実際に使用された割合（目標: 40%以上）
- **改善倍率**: Linux ReadAheadとの比較（論文目標: 1.31-1.91x）

## � 詳細情報

- **シミュレーション詳細**: `documents/SIMULATION_OVERVIEW.md`
- **技術仕様**: `documents/REQUIREMENTS_DEFINITION.md`
- **用語解説**: `documents/TERMINOLOGY_GUIDE.md`

---
**CluMP Simulator** - 論文準拠ストレージI/O最適化シミュレータ 🚀