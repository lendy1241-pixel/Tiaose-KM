#!/usr/bin/env python3
"""
色浆配方求解器 — 给定目标色，自动搜索最优色浆配比
用途: 验证你的调色结果是否接近最优解，或者生成训练用的"标准答案"
"""

import math
import random
import itertools
from km_engine import (
    KMEngine, KMMixResult, Pigment, WAVELENGTHS, NUM_BANDS,
    create_pigment, create_all_pigments, mix_pigments,
    PIGMENT_DEFS, D65, CIE_X, CIE_Y, CIE_Z,
)
from km_engine import _K_NORMALIZE


class FormulaSolver:
    """用优化算法搜索最佳色浆配比"""

    def __init__(self, available_pigments: list[str], base_weight: float = 200.0):
        """
        available_pigments: 可用色浆名称列表 (不含钛白，钛白自动加入)
        base_weight: 钛白基础重量 (g)
        """
        self.base_weight = base_weight
        # 钛白总是可用
        self.tint_names = [n for n in available_pigments if n != "钛白"]
        self.all_names = ["钛白"] + self.tint_names
        self.pigments = {n: create_pigment(n) for n in self.all_names}

    def evaluate(self, weights: dict[str, float], target_lab: tuple) -> float:
        """评估配方，返回 ΔE00 (越小越好)"""
        result = KMEngine.mix(
            [self.pigments[n] for n in self.all_names if weights.get(n, 0) > 0.001],
            [weights.get(n, 0) for n in self.all_names if weights.get(n, 0) > 0.001]
        )
        return KMEngine.delta_e_2000(*target_lab, result.L, result.a, result.b)

    def random_search(self, target_hex: str, iterations: int = 5000) -> tuple[dict, float]:
        """
        随机搜索 — 快速但不够精确，适合探索解空间
        """
        target_lab = self._hex_to_lab(target_hex)

        best_weights = None
        best_de = float('inf')

        for _ in range(iterations):
            weights = {"钛白": self.base_weight}
            for name in self.tint_names:
                # 色浆用量: 对数均匀分布 (大部分搜索小用量)
                if random.random() < 0.3:
                    weights[name] = 0  # 30% 概率不用这种色浆
                else:
                    weights[name] = 10 ** random.uniform(-1, 1.7)  # 0.1g ~ 50g

            de = self.evaluate(weights, target_lab)
            if de < best_de:
                best_de = de
                best_weights = weights.copy()

        return best_weights, best_de

    def hill_climb(self, target_hex: str, initial: dict = None,
                   steps: int = 500, step_size: float = 0.5) -> tuple[dict, float]:
        """
        爬山法 — 从初始点局部优化
        """
        target_lab = self._hex_to_lab(target_hex)

        if initial is None:
            current = {"钛白": self.base_weight}
            for name in self.tint_names:
                current[name] = 1.0
        else:
            current = initial.copy()

        current_de = self.evaluate(current, target_lab)

        for _ in range(steps):
            # 随机扰动
            candidate = current.copy()
            for name in self.all_names:
                perturbation = random.uniform(-step_size, step_size)
                candidate[name] = max(0, candidate[name] + perturbation)
                # 确保总重合理
                if candidate[name] > 200:
                    candidate[name] = 200

            candidate_de = self.evaluate(candidate, target_lab)
            if candidate_de < current_de:
                current = candidate
                current_de = candidate_de
            # 模拟退火: 小概率接受更差解 (帮助跳出局部最优)
            elif random.random() < 0.05:
                current = candidate
                current_de = candidate_de

        return current, current_de

    def exhaustive_grid(self, target_hex: str, grid_size: int = 6) -> tuple[dict, float]:
        """
        网格搜索 — 对 2-3 种色浆的精确搜索
        如果色浆太多 (>4种) 会非常慢
        """
        if len(self.tint_names) > 4:
            raise ValueError(f"网格搜索最多 4 种色浆，当前有 {len(self.tint_names)} 种。请用 random_search 代替。")

        target_lab = self._hex_to_lab(target_hex)
        best_weights = None
        best_de = float('inf')

        # 每种色浆的用量范围: 0, 0.5, 1, 2, 5, 10, 20, 50
        levels = [0, 0.3, 0.6, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]

        # 减少 grid 以控制复杂度
        levels = levels[:grid_size + 3]

        for combo in itertools.product(levels, repeat=len(self.tint_names)):
            weights = {"钛白": self.base_weight}
            for i, name in enumerate(self.tint_names):
                weights[name] = combo[i]

            # 跳过全零
            if sum(weights.values()) <= self.base_weight + 0.001:
                continue

            de = self.evaluate(weights, target_lab)
            if de < best_de:
                best_de = de
                best_weights = weights.copy()

        return best_weights, best_de

    def solve(self, target_hex: str,
              method: str = "auto",
              time_budget: float = 2.0) -> dict:
        """
        全自动求解。
        method: "auto" | "random" | "hill" | "grid"
        返回: {"formula": {...}, "delta_e": ..., "result": KMMixResult}
        """
        print(f"\n🎯 目标色: {target_hex}")
        target_lab = self._hex_to_lab(target_hex)
        print(f"   LAB: L*={target_lab[0]:.1f}, a*={target_lab[1]:.1f}, b*={target_lab[2]:.1f}")
        print(f"   可用色浆: {self.all_names}")
        print(f"   钛白基料: {self.base_weight}g")

        # 阶段 1: 随机搜索 (探索)
        print(f"\n🔍 阶段 1: 随机搜索 (5000 次)...")
        w1, de1 = self.random_search(target_hex, iterations=5000)
        print(f"   最佳 ΔE00 = {de1:.2f}")
        self._print_formula(w1)

        # 阶段 2: 爬山优化 (精调)
        print(f"\n⛰️  阶段 2: 爬山优化 (500 步)...")
        w2, de2 = self.hill_climb(target_hex, initial=w1, steps=500, step_size=0.2)
        print(f"   最终 ΔE00 = {de2:.2f}")
        self._print_formula(w2)

        # 阶段 3: 如果色浆种类少，网格搜索确保全局最优
        if len(self.tint_names) <= 3:
            print(f"\n📐 阶段 3: 网格搜索 (精确)...")
            w3, de3 = self.exhaustive_grid(target_hex, grid_size=5)
            print(f"   网格最优 ΔE00 = {de3:.2f}")
            if de3 < de2:
                w2, de2 = w3, de3
                print(f"   → 采纳网格搜索结果")
            self._print_formula(w3)

        # 最终结果
        final_result = KMEngine.mix(
            [self.pigments[n] for n in self.all_names if w2.get(n, 0) > 0.01],
            [w2.get(n, 0) for n in self.all_names if w2.get(n, 0) > 0.01]
        )

        # ΔE 等级评定
        if de2 < 1.0:
            grade = "🏆 完美! 肉眼无法分辨"
        elif de2 < 3.0:
            grade = "✅ 优秀! 工业级可接受"
        elif de2 < 6.0:
            grade = "👍 良好! 可见差异但可接受"
        elif de2 < 12.0:
            grade = "⚠️ 一般! 明显色差"
        else:
            grade = "❌ 较差! 需要更多色浆种类"

        print(f"\n{'='*50}")
        print(f"  最终配方")
        print(f"{'='*50}")
        self._print_formula(w2)
        print(f"  混合结果: HEX={final_result.hex}")
        print(f"            LAB=({final_result.L:.1f}, {final_result.a:.1f}, {final_result.b:.1f})")
        print(f"  ΔE00 = {de2:.2f}")
        print(f"  评定: {grade}")
        print()

        return {
            "formula": {n: w for n, w in w2.items() if w > 0.01},
            "delta_e": de2,
            "result": final_result,
        }

    def _print_formula(self, weights: dict):
        items = [(n, w) for n, w in weights.items() if w > 0.01]
        items.sort(key=lambda x: -x[1])
        parts = [f"{n}: {w:.1f}g" for n, w in items]
        print(f"   配方: {' + '.join(parts)}")

    @staticmethod
    def _hex_to_lab(hex_str: str) -> tuple:
        h = hex_str.lstrip('#')
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return KMEngine.srgb_to_lab(r, g, b)


# ============================================================
# 演示
# ============================================================

def main():
    print("=" * 60)
    print("  色浆配方求解器")
    print("=" * 60)

    # --- 演示 1: 暖橙色 ---
    solver = FormulaSolver(
        available_pigments=["钛白", "铁红", "铬黄", "永固红", "酞青蓝", "炭黑"],
        base_weight=200.0,
    )
    result = solver.solve("#E8B4A2", method="auto")

    # --- 演示 2: 军绿色 ---
    solver2 = FormulaSolver(
        available_pigments=["钛白", "铬黄", "酞青蓝", "炭黑", "铁红"],
        base_weight=200.0,
    )
    result2 = solver2.solve("#6B7B3A", method="auto")

    # --- 演示 3: 裸粉色 (挑战较大) ---
    solver3 = FormulaSolver(
        available_pigments=["钛白", "铁红", "永固红", "铬黄", "炭黑", "群青"],
        base_weight=200.0,
    )
    result3 = solver3.solve("#D4A0A0", method="auto")

    print("\n" + "=" * 60)
    print("  求解完成! 这些配方可直接用于训练。")
    print("=" * 60)


if __name__ == "__main__":
    main()
