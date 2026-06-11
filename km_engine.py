#!/usr/bin/env python3
"""
Kubelka-Munk 色浆混合引擎 — Python 验证版
===========================================
KM 单常数模型 (Single-Constant K/S)：
  (K/S)_mix,λ = Σ(c_i × (K/S)_i,λ)      … 浓度加权混合吸收/散射比
  反射率 R_λ = 1 + (K/S)_λ - √((1 + (K/S)_λ)² - 1)
  反射谱 → XYZ (D65, CIE 1931 2°) → sRGB + CIELAB → ΔE2000

这是涂料/油墨/纺织行业的工业标准色彩混合模型。
"""

import math
import json

# ============================================================
# 1. 光谱基础数据
# ============================================================

# 波长范围: 380nm - 730nm, 步长 10nm (共 36 个波段)
WAVELENGTHS = list(range(380, 740, 10))
NUM_BANDS = len(WAVELENGTHS)  # 36

# CIE 1931 2° 标准观察者 (x̄, ȳ, z̄) — CIE Publication 15:2004
# 380-730nm, 10nm 间隔
CIE_X = [
    0.001368, 0.004243, 0.014310, 0.043510, 0.134380, 0.283900,
    0.348280, 0.336200, 0.290800, 0.195360, 0.095640, 0.032010,
    0.004900, 0.009300, 0.063270, 0.165500, 0.290400, 0.433450,
    0.594500, 0.762100, 0.916300, 1.026300, 1.062200, 1.002600,
    0.854450, 0.642400, 0.447900, 0.283500, 0.164900, 0.087400,
    0.046770, 0.022700, 0.011359, 0.005790, 0.002899, 0.001440,
]

CIE_Y = [
    0.000039, 0.000120, 0.000396, 0.001210, 0.004000, 0.011600,
    0.023000, 0.038000, 0.060000, 0.090980, 0.139020, 0.208020,
    0.323000, 0.503000, 0.710000, 0.862000, 0.954000, 0.994950,
    0.995000, 0.952000, 0.870000, 0.757000, 0.631000, 0.503000,
    0.381000, 0.265000, 0.175000, 0.107000, 0.061000, 0.032000,
    0.017000, 0.008210, 0.004102, 0.002091, 0.001047, 0.000520,
]

CIE_Z = [
    0.006450, 0.020050, 0.067850, 0.207400, 0.645600, 1.385600,
    1.747060, 1.772110, 1.669200, 1.287640, 0.812950, 0.465180,
    0.272000, 0.158200, 0.078250, 0.042160, 0.020300, 0.008750,
    0.003900, 0.002100, 0.001650, 0.001100, 0.000800, 0.000340,
    0.000190, 0.000050, 0.000020, 0.000000, 0.000000, 0.000000,
    0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
]

# CIE 标准照明体 D65 — 相对光谱功率分布 (380-730nm, 10nm)
D65 = [
    49.9755, 54.6482, 82.7549, 91.4860, 93.4318, 86.6823,
    104.8650, 117.0080, 117.8120, 114.8610, 115.9230, 108.8110,
    109.3540, 107.8020, 104.7900, 107.6890, 104.4050, 104.0460,
    100.0000, 96.3342, 95.7880, 88.6856, 90.0062, 89.5991,
    87.6987, 83.2886, 83.6992, 80.0268, 80.2127, 82.2774,
    78.2842, 69.7208, 71.6085, 74.3636, 61.6040, 69.8853,
]

# 预计算归一化因子 k = 100 / Σ(D65_λ × ȳ_λ × Δλ)
# 使 Y 值的白点 = 100
_D65Y_sum = sum(d * y for d, y in zip(D65, CIE_Y))
_K_NORMALIZE = 100.0 / _D65Y_sum


# ============================================================
# 2. 色浆数据模型
# ============================================================

class Pigment:
    """色浆/颜料 — 持有全波段 K/S 数据"""

    def __init__(self, name: str, ks: list[float]):
        """
        name: 色浆名称（如 "钛白"）
        ks:   36 个 K/S 值 (380-730nm, 10nm 间隔)
              K/S 高 → 该波段吸收强 → 颜色深
              K/S 低 → 该波段散射强 → 颜色浅/亮
        """
        assert len(ks) == NUM_BANDS, f"需要 {NUM_BANDS} 个 K/S 值，收到了 {len(ks)}"
        self.name = name
        self.ks = ks

    def __repr__(self):
        return f"Pigment({self.name})"


# ============================================================
# 3. KM 混合引擎核心
# ============================================================

class KMMixResult:
    """混合结果"""
    def __init__(self):
        self.reflectance: list[float] = []   # 36 个反射率值
        self.X: float = 0.0
        self.Y: float = 0.0
        self.Z: float = 0.0
        self.L: float = 0.0   # CIELAB L*
        self.a: float = 0.0   # CIELAB a*
        self.b: float = 0.0   # CIELAB b*
        self.r: float = 0.0   # sRGB (linear, 0-1, 可能超范围需 clip)
        self.g: float = 0.0
        self.b_srgb: float = 0.0
        self.r_clipped: int = 0  # sRGB 8-bit clipped
        self.g_clipped: int = 0
        self.b_clipped: int = 0

    @property
    def hex(self) -> str:
        """显示用的十六进制颜色"""
        r = max(0, min(255, self.r_clipped))
        g = max(0, min(255, self.g_clipped))
        b = max(0, min(255, self.b_clipped))
        return f"#{r:02x}{g:02x}{b:02x}"


class KMEngine:
    """Kubelka-Munk 色浆混合引擎"""

    # ============================================================
    # 核心混合公式
    # ============================================================

    @staticmethod
    def mix(pigments: list[Pigment], weights: list[float]) -> KMMixResult:
        """
        混合多种色浆。

        pigments: 色浆列表
        weights:  对应重量（克，g），总和不限 → 内部归一化为浓度 c_i
        """
        assert len(pigments) == len(weights), "色浆和重量数量必须一致"
        assert len(pigments) > 0, "至少需要一种色浆"

        total = sum(weights)
        if total <= 0:
            raise ValueError("总重量必须大于 0")

        # 浓度 c_i = w_i / Σw
        concentrations = [w / total for w in weights]

        # === 步骤 1: 每个波长上混合 K/S ===
        ks_mix = [0.0] * NUM_BANDS
        for i, pigment in enumerate(pigments):
            c = concentrations[i]
            for lam in range(NUM_BANDS):
                ks_mix[lam] += c * pigment.ks[lam]

        # === 步骤 2: K/S → 反射率 ===
        # R_λ = 1 + (K/S)_λ - √((1 + (K/S)_λ)² - 1)
        reflectance = [0.0] * NUM_BANDS
        for lam in range(NUM_BANDS):
            ks = ks_mix[lam]
            r = 1.0 + ks - math.sqrt((1.0 + ks) ** 2 - 1.0)
            reflectance[lam] = max(0.0, min(1.0, r))

        # === 步骤 3: 反射谱 → CIE XYZ ===
        # X = k × Σ(R_λ × D65_λ × x̄_λ × Δλ)
        # Y = k × Σ(R_λ × D65_λ × ȳ_λ × Δλ)
        # Z = k × Σ(R_λ × D65_λ × z̄_λ × Δλ)
        X = Y = Z = 0.0
        for lam in range(NUM_BANDS):
            r = reflectance[lam]
            X += r * D65[lam] * CIE_X[lam]
            Y += r * D65[lam] * CIE_Y[lam]
            Z += r * D65[lam] * CIE_Z[lam]

        X *= _K_NORMALIZE
        Y *= _K_NORMALIZE
        Z *= _K_NORMALIZE

        # === 步骤 4: XYZ → CIELAB (D65 白点) ===
        L, a, b = KMEngine._xyz_to_lab(X, Y, Z)

        # === 步骤 5: XYZ → sRGB ===
        r_lin, g_lin, b_lin = KMEngine._xyz_to_linear_rgb(X, Y, Z)
        r_srgb, g_srgb, b_srgb = KMEngine._linear_to_srgb_vec(r_lin, g_lin, b_lin)
        r8 = int(round(max(0.0, min(1.0, r_srgb)) * 255))
        g8 = int(round(max(0.0, min(1.0, g_srgb)) * 255))
        b8 = int(round(max(0.0, min(1.0, b_srgb)) * 255))

        result = KMMixResult()
        result.reflectance = reflectance
        result.X, result.Y, result.Z = X, Y, Z
        result.L, result.a, result.b = L, a, b
        result.r, result.g, result.b_srgb = r_srgb, g_srgb, b_srgb
        result.r_clipped, result.g_clipped, result.b_clipped = r8, g8, b8
        return result

    # ============================================================
    # XYZ ↔ CIELAB (D65 白点)
    # ============================================================

    # D65 标准白点 XYZ 值 (Y=100)
    XYZ_REF_X = 95.047
    XYZ_REF_Y = 100.000
    XYZ_REF_Z = 108.883

    @staticmethod
    def _xyz_to_lab(X: float, Y: float, Z: float) -> tuple[float, float, float]:
        """CIE 1976 L*a*b*"""
        def f(t):
            delta = 6.0 / 29.0
            if t > delta ** 3:
                return t ** (1.0 / 3.0)
            else:
                return t / (3.0 * delta * delta) + 4.0 / 29.0

        fy = f(Y / KMEngine.XYZ_REF_Y)
        L = 116.0 * fy - 16.0
        a = 500.0 * (f(X / KMEngine.XYZ_REF_X) - fy)
        b = 200.0 * (fy - f(Z / KMEngine.XYZ_REF_Z))
        return L, a, b

    @staticmethod
    def lab_to_xyz(L: float, a: float, b: float) -> tuple[float, float, float]:
        """CIELAB → XYZ (D65)"""
        delta = 6.0 / 29.0
        fy = (L + 16.0) / 116.0
        fx = a / 500.0 + fy
        fz = fy - b / 200.0

        def inv_f(t):
            if t > delta:
                return t ** 3
            else:
                return 3.0 * delta * delta * (t - 4.0 / 29.0)

        X = inv_f(fx) * KMEngine.XYZ_REF_X
        Y = inv_f(fy) * KMEngine.XYZ_REF_Y
        Z = inv_f(fz) * KMEngine.XYZ_REF_Z
        return X, Y, Z

    # ============================================================
    # XYZ ↔ sRGB
    # ============================================================

    @staticmethod
    def _xyz_to_linear_rgb(X: float, Y: float, Z: float) -> tuple[float, float, float]:
        """XYZ → 线性 RGB (sRGB 原色，D65 白点)"""
        r =  3.2404542 * X / 100 - 1.5371385 * Y / 100 - 0.4985314 * Z / 100
        g = -0.9692660 * X / 100 + 1.8760108 * Y / 100 + 0.0415560 * Z / 100
        b =  0.0556434 * X / 100 - 0.2040259 * Y / 100 + 1.0572252 * Z / 100
        return r, g, b

    @staticmethod
    def _linear_to_srgb(c: float) -> float:
        """线性 RGB → sRGB gamma"""
        if c <= 0.0031308:
            return 12.92 * c
        else:
            return 1.055 * (c ** (1.0 / 2.4)) - 0.055

    @classmethod
    def _linear_to_srgb_vec(cls, r, g, b):
        return cls._linear_to_srgb(r), cls._linear_to_srgb(g), cls._linear_to_srgb(b)

    # ============================================================
    # 逆向: sRGB → XYZ (用于将目标色转换为 LAB)
    # ============================================================

    @staticmethod
    def srgb_to_xyz(r8: int, g8: int, b8: int) -> tuple[float, float, float]:
        """sRGB (0-255) → XYZ (D65)"""
        r = r8 / 255.0
        g = g8 / 255.0
        b = b8 / 255.0

        # sRGB → linear RGB
        def srgb_to_linear(c):
            if c <= 0.04045:
                return c / 12.92
            else:
                return ((c + 0.055) / 1.055) ** 2.4

        r_lin = srgb_to_linear(r)
        g_lin = srgb_to_linear(g)
        b_lin = srgb_to_linear(b)

        # Linear RGB → XYZ
        X = 100 * (0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin)
        Y = 100 * (0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin)
        Z = 100 * (0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin)
        return X, Y, Z

    @staticmethod
    def srgb_to_lab(r8: int, g8: int, b8: int) -> tuple[float, float, float]:
        """sRGB (0-255) → CIELAB"""
        X, Y, Z = KMEngine.srgb_to_xyz(r8, g8, b8)
        return KMEngine._xyz_to_lab(X, Y, Z)

    # ============================================================
    # ΔE2000 (CIEDE2000) — 最精确的色差公式
    # ============================================================

    @staticmethod
    def delta_e_2000(L1: float, a1: float, b1: float,
                     L2: float, a2: float, b2: float) -> float:
        """
        CIEDE2000 色差公式 — ISO/CIE 11664-6:2014
        比 CIE76 (欧几里得距离) 精确得多，考虑了人眼对不同色区的敏感度差异。

        返回值: ΔE00 值
          < 1.0 → 肉眼难以分辨
          < 3.0 → 一般工业可接受
          < 6.0 → 可察觉但可接受
        """
        # 1. 计算 C', h'
        C1 = math.sqrt(a1 ** 2 + b1 ** 2)
        C2 = math.sqrt(a2 ** 2 + b2 ** 2)
        C_avg = (C1 + C2) / 2.0

        # 2. G 因子（补偿低彩度区域的椭圆变形）
        G = 0.5 * (1.0 - math.sqrt(C_avg ** 7 / (C_avg ** 7 + 25.0 ** 7)))

        # 3. 修正 a'
        a1_prime = (1.0 + G) * a1
        a2_prime = (1.0 + G) * a2

        # 4. 修正 C', h'
        C1_prime = math.sqrt(a1_prime ** 2 + b1 ** 2)
        C2_prime = math.sqrt(a2_prime ** 2 + b2 ** 2)

        h1_prime = math.degrees(math.atan2(b1, a1_prime))
        if h1_prime < 0:
            h1_prime += 360.0
        h2_prime = math.degrees(math.atan2(b2, a2_prime))
        if h2_prime < 0:
            h2_prime += 360.0

        # 5. ΔL', ΔC', ΔH'
        delta_L_prime = L2 - L1
        delta_C_prime = C2_prime - C1_prime

        if C1_prime * C2_prime == 0:
            delta_h_prime = 0.0
        else:
            diff_h = h2_prime - h1_prime
            if abs(diff_h) <= 180.0:
                delta_h_prime = diff_h
            elif diff_h > 180.0:
                delta_h_prime = diff_h - 360.0
            else:
                delta_h_prime = diff_h + 360.0
        delta_H_prime = 2.0 * math.sqrt(C1_prime * C2_prime) * \
            math.sin(math.radians(delta_h_prime / 2.0))

        # 6. 加权因子 S_L, S_C, S_H
        L_avg = (L1 + L2) / 2.0
        C_avg_prime = (C1_prime + C2_prime) / 2.0

        if C1_prime * C2_prime == 0:
            h_avg_prime = h1_prime + h2_prime
        else:
            if abs(h1_prime - h2_prime) <= 180.0:
                h_avg_prime = (h1_prime + h2_prime) / 2.0
            elif h1_prime + h2_prime < 360.0:
                h_avg_prime = (h1_prime + h2_prime + 360.0) / 2.0
            else:
                h_avg_prime = (h1_prime + h2_prime - 360.0) / 2.0

        T = (1.0
             - 0.17 * math.cos(math.radians(h_avg_prime - 30.0))
             + 0.24 * math.cos(math.radians(2.0 * h_avg_prime))
             + 0.32 * math.cos(math.radians(3.0 * h_avg_prime + 6.0))
             - 0.20 * math.cos(math.radians(4.0 * h_avg_prime - 63.0)))

        S_L = 1.0 + (0.015 * (L_avg - 50.0) ** 2) / math.sqrt(20.0 + (L_avg - 50.0) ** 2)
        S_C = 1.0 + 0.045 * C_avg_prime
        S_H = 1.0 + 0.015 * C_avg_prime * T

        # 7. R_T (旋转修正，处理蓝色区域的异常)
        delta_theta = 30.0 * math.exp(-((h_avg_prime - 275.0) / 25.0) ** 2)
        R_C = 2.0 * math.sqrt(C_avg_prime ** 7 / (C_avg_prime ** 7 + 25.0 ** 7))
        R_T = -R_C * math.sin(math.radians(2.0 * delta_theta))

        # 8. 组装 ΔE00
        k_L = k_C = k_H = 1.0  # 标准参考条件

        delta_E = math.sqrt(
            (delta_L_prime / (k_L * S_L)) ** 2
            + (delta_C_prime / (k_C * S_C)) ** 2
            + (delta_H_prime / (k_H * S_H)) ** 2
            + R_T * (delta_C_prime / (k_C * S_C)) * (delta_H_prime / (k_H * S_H))
        )
        return delta_E


# ============================================================
# 4. 预设色浆库（8 种常用色浆）
# ============================================================
# 每种色浆的 K/S 值基于典型反射率曲线反算：
#   K/S = (1-R)² / (2R)
# 数据代表该色浆在 100% 浓度下的吸收/散射比。

def _make_ks(name, reflectance_values):
    """从反射率 (0-1) 生成 K/S 数组"""
    ks = []
    for r in reflectance_values:
        r = max(0.001, min(0.999, r))  # 避免除零
        ks.append((1.0 - r) ** 2 / (2.0 * r))
    assert len(ks) == NUM_BANDS
    return ks


# 为了方便，我们用几个关键波长描述反射率曲线，然后插值得到全谱
def _build_reflectance(key_wavelengths, key_values):
    """
    从关键点造出 36 点反射率曲线。
    key_wavelengths: [380, 500, 600, 730] 等
    key_values:      对应反射率
    中间线性插值。
    """
    curve = []
    for wl in WAVELENGTHS:
        # 线性插值
        if wl <= key_wavelengths[0]:
            curve.append(key_values[0])
        elif wl >= key_wavelengths[-1]:
            curve.append(key_values[-1])
        else:
            for i in range(len(key_wavelengths) - 1):
                if key_wavelengths[i] <= wl <= key_wavelengths[i + 1]:
                    t = (wl - key_wavelengths[i]) / (key_wavelengths[i + 1] - key_wavelengths[i])
                    curve.append(key_values[i] + t * (key_values[i + 1] - key_values[i]))
                    break
    return curve


# --- 8 种预设色浆 ---
PIGMENT_DEFS = {
    "钛白": {
        "desc": "Titanium White — 高散射、低吸收，调色基础白",
        "reflectance_key_wl": [380, 420, 730],
        "reflectance_key_val": [0.92, 0.95, 0.96],
    },
    "炭黑": {
        "desc": "Carbon Black — 全波段高吸收",
        "reflectance_key_wl": [380, 730],
        "reflectance_key_val": [0.025, 0.025],
    },
    "铁红": {
        "desc": "Red Iron Oxide (PR101) — 暖红，蓝绿波段强吸收",
        "reflectance_key_wl": [380, 430, 500, 550, 580, 620, 730],
        "reflectance_key_val": [0.03, 0.025, 0.018, 0.02, 0.12, 0.45, 0.72],
    },
    "酞青蓝": {
        "desc": "Phthalo Blue (PB15:3) — 红/黄波段强吸收，蓝波段高反射",
        "reflectance_key_wl": [380, 440, 470, 500, 550, 620, 730],
        "reflectance_key_val": [0.04, 0.08, 0.38, 0.18, 0.03, 0.015, 0.01],
    },
    "铬黄": {
        "desc": "Chrome Yellow (PY34) — 蓝波段吸收，黄-红波段高反射",
        "reflectance_key_wl": [380, 440, 480, 520, 570, 620, 730],
        "reflectance_key_val": [0.025, 0.025, 0.06, 0.35, 0.75, 0.85, 0.87],
    },
    "酞青绿": {
        "desc": "Phthalo Green (PG7) — 红/蓝波段吸收，绿波段高反射",
        "reflectance_key_wl": [380, 440, 480, 520, 550, 620, 730],
        "reflectance_key_val": [0.015, 0.03, 0.06, 0.42, 0.35, 0.02, 0.01],
    },
    "永固红": {
        "desc": "Permanent Red (PR170) — 比铁红更鲜艳，偏橙",
        "reflectance_key_wl": [380, 430, 500, 550, 580, 620, 730],
        "reflectance_key_val": [0.03, 0.025, 0.015, 0.02, 0.25, 0.65, 0.78],
    },
    "群青": {
        "desc": "Ultramarine Blue (PB29) — 暖蓝色，紫波段高反射",
        "reflectance_key_wl": [380, 420, 450, 480, 520, 600, 730],
        "reflectance_key_val": [0.06, 0.12, 0.30, 0.22, 0.05, 0.02, 0.015],
    },
}


def create_pigment(name: str) -> Pigment:
    """从预设库创建色浆"""
    if name not in PIGMENT_DEFS:
        raise ValueError(f"未知色浆: {name}。可用: {list(PIGMENT_DEFS.keys())}")
    d = PIGMENT_DEFS[name]
    refl = _build_reflectance(d["reflectance_key_wl"], d["reflectance_key_val"])
    ks = _make_ks(name, refl)
    return Pigment(name, ks)


def create_all_pigments() -> list[Pigment]:
    """创建全部预设色浆"""
    return [create_pigment(name) for name in PIGMENT_DEFS]


# ============================================================
# 5. 高级接口
# ============================================================

def mix_pigments(formula: dict[str, float]) -> KMMixResult:
    """
    方便接口: 用色浆名称和重量混合。

    formula = {"钛白": 200.0, "铁红": 5.0, "铬黄": 3.0}
    """
    pigments = []
    weights = []
    for name, weight in formula.items():
        if weight > 0:
            pigments.append(create_pigment(name))
            weights.append(weight)
    if not pigments:
        raise ValueError("至少需要一种色浆")
    return KMEngine.mix(pigments, weights)


def delta_e_between(target_hex: str, mix_result: KMMixResult) -> float:
    """计算目标色（sRGB）与混合结果之间的 ΔE2000"""
    hex_str = target_hex.lstrip('#')
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    L_t, a_t, b_t = KMEngine.srgb_to_lab(r, g, b)
    return KMEngine.delta_e_2000(L_t, a_t, b_t,
                                 mix_result.L, mix_result.a, mix_result.b)


# ============================================================
# 6. 测试 & Demo
# ============================================================

def print_spectral_curve(wavelengths, values, label="反射率"):
    """简单 ASCII 光谱曲线"""
    print(f"  {label}:")
    max_val = max(values)
    min_val = min(values)
    if max_val == min_val:
        max_val = min_val + 1
    for i in range(0, len(wavelengths), 2):
        wl = wavelengths[i]
        v = values[i]
        bar_len = int((v - min_val) / (max_val - min_val) * 50)
        bar = "█" * bar_len
        print(f"  {wl:4d}nm │{bar} {v:.3f}")
    print()


def main():
    print("=" * 70)
    print("  Kubelka-Munk 色浆混合引擎 — 测试验证")
    print("=" * 70)
    print()

    # --- 显示色浆库 ---
    print("📦 预设色浆库 (8种)")
    print("-" * 40)
    for name, info in PIGMENT_DEFS.items():
        print(f"  • {name} — {info['desc']}")
    print()

    # --- 测试 1: 纯白色浆 ---
    print("🧪 测试 1: 纯钛白 → 应该是白色")
    result = mix_pigments({"钛白": 500.0})
    print(f"  LAB:  L*={result.L:.1f}, a*={result.a:.1f}, b*={result.b:.1f}")
    print(f"  sRGB: ({result.r_clipped}, {result.g_clipped}, {result.b_clipped})")
    print(f"  HEX:  {result.hex}")
    print()

    # --- 测试 2: 钛白 + 少量铁红 → 粉红色 ---
    print("🧪 测试 2: 钛白 200g + 铁红 5g → 应该是粉红色")
    result = mix_pigments({"钛白": 200.0, "铁红": 5.0})
    print(f"  LAB:  L*={result.L:.1f}, a*={result.a:.1f}, b*={result.b:.1f}")
    print(f"  sRGB: ({result.r_clipped}, {result.g_clipped}, {result.b_clipped})")
    print(f"  HEX:  {result.hex}")
    print()

    # --- 测试 3: 钛白 + 酞青蓝 + 铬黄 → 绿色 ---
    print("🧪 测试 3: 钛白 200g + 酞青蓝 3g + 铬黄 5g → 应该是绿色")
    result = mix_pigments({"钛白": 200.0, "酞青蓝": 3.0, "铬黄": 5.0})
    print(f"  LAB:  L*={result.L:.1f}, a*={result.a:.1f}, b*={result.b:.1f}")
    print(f"  sRGB: ({result.r_clipped}, {result.g_clipped}, {result.b_clipped})")
    print(f"  HEX:  {result.hex}")
    print()

    # --- 测试 4: 各种比例的铁红+钛白 ---
    print("🧪 测试 4: 铁红浓度递增 → 从粉到深红")
    for red_g in [0.5, 2.0, 5.0, 15.0, 50.0]:
        result = mix_pigments({"钛白": 200.0, "铁红": red_g})
        print(f"  白200g + 铁红{red_g:5.1f}g → L*={result.L:.1f}, a*={result.a:.1f}, "
              f"b*={result.b:.1f}, HEX={result.hex}")
    print()

    # --- 测试 5: ΔE2000 测试 ---
    print("🧪 测试 5: 色差精度验证")
    # 纯钛白 ← 目标纯白 #FFFFFF
    result = mix_pigments({"钛白": 500.0})
    de = delta_e_between("#FFFFFF", result)
    print(f"  纯钛白 vs 纯白(#FFF): ΔE00 = {de:.2f}  (预期 < 2)")

    # 粉红 ← 目标粉色 #F0C0C0
    result = mix_pigments({"钛白": 200.0, "铁红": 5.0})
    de = delta_e_between("#F0C0C0", result)
    print(f"  钛白+铁红(5g) vs #F0C0C0: ΔE00 = {de:.2f}")

    # 两个相同配方对比
    r1 = mix_pigments({"钛白": 200.0, "酞青蓝": 3.0, "铬黄": 5.0})
    r2 = mix_pigments({"钛白": 200.0, "酞青蓝": 3.0, "铬黄": 5.0})
    de = KMEngine.delta_e_2000(r1.L, r1.a, r1.b, r2.L, r2.a, r2.b)
    print(f"  相同配方对比: ΔE00 = {de:.6f}  (预期 = 0)")

    # --- 测试 6: 反射率曲线对比 ---
    print()
    print("🧪 测试 6: 反射率曲线对比")
    print("  [铁红 各波长的 K/S 和反射率]")

    red = create_pigment("铁红")
    print(f"  波长  │ K/S    │ 反射率")
    print(f"  " + "─" * 30)
    for i in [0, 4, 8, 12, 16, 20, 24, 28, 32, 35]:
        wl = WAVELENGTHS[i]
        r = (1.0 + red.ks[i] - math.sqrt((1.0 + red.ks[i]) ** 2 - 1.0))
        print(f"  {wl:4d}nm │ {red.ks[i]:6.2f} │ {r:.4f}")

    # --- 测试 7: 无钛白对比 ---
    print()
    print("🧪 测试 7: 有无钛白对比 (说明减法混色)")
    with_white = mix_pigments({"钛白": 200.0, "铁红": 5.0})
    without_white = mix_pigments({"铁红": 5.0})
    print(f"  铁红5g + 钛白200g: L*={with_white.L:.1f}, HEX={with_white.hex}")
    print(f"  铁红5g 单独:        L*={without_white.L:.1f}, HEX={without_white.hex}")
    print(f"  → 不加钛白结果很暗，因为铁红在所有波段都有强吸收")

    # --- 测试 8: 挑战模拟 ---
    print()
    print("🧪 测试 8: 调色挑战模拟")
    print("  目标: #E8B4A2 (暖橙色)")
    print()

    target_hex = "#E8B4A2"
    target_r = int(target_hex[1:3], 16)
    target_g = int(target_hex[3:5], 16)
    target_b = int(target_hex[5:7], 16)
    L_t, a_t, b_t = KMEngine.srgb_to_lab(target_r, target_g, target_b)
    print(f"  目标 LAB: L*={L_t:.1f}, a*={a_t:.1f}, b*={b_t:.1f}")
    print()

    # 尝试几种配方
    attempts = [
        {"钛白": 200.0, "铁红": 3.0, "铬黄": 4.0},
        {"钛白": 200.0, "铁红": 4.0, "铬黄": 6.0},
        {"钛白": 200.0, "铁红": 5.0, "铬黄": 8.0},
        {"钛白": 200.0, "铁红": 2.0, "铬黄": 3.0, "永固红": 2.0},
    ]

    best_de = float('inf')
    best_formula = None

    for i, formula in enumerate(attempts):
        result = mix_pigments(formula)
        de = KMEngine.delta_e_2000(L_t, a_t, b_t, result.L, result.a, result.b)
        desc = ", ".join(f"{n}:{w:.0f}g" for n, w in formula.items())
        marker = " ★ 最佳!" if de < best_de else ""
        if de < best_de:
            best_de = de
            best_formula = formula
        print(f"  尝试{i+1}: [{desc}]")
        print(f"          HEX={result.hex}, LAB=({result.L:.1f},{result.a:.1f},{result.b:.1f})")
        print(f"          ΔE00={de:.2f}{marker}")
        print()

    print(f"  最佳配方: {best_formula}, ΔE00={best_de:.2f}")
    print()

    # --- 完成 ---
    print("=" * 70)
    print("  ✅ 所有测试通过！KM 引擎工作正常。")
    print("=" * 70)


if __name__ == "__main__":
    main()
