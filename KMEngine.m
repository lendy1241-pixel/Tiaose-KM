//
//  KMEngine.m — Kubelka-Munk 色浆混合引擎实现
//
//  参考标准:
//    CIE Publication 15:2004 (Colorimetry)
//    ISO/CIE 11664-6:2014 (CIEDE2000)
//    Kubelka-Munk 单常数模型 (涂料/油墨工业标准)
//

#import "KMEngine.h"
#import <math.h>

// ============================================================
// CIE 1931 2° 标准观察者 (x̄, ȳ, z̄) — 380-730nm, 10nm 步长
// ============================================================
static const CGFloat CIE_X[KM_SPECTRAL_BANDS] = {
    0.001368f, 0.004243f, 0.014310f, 0.043510f, 0.134380f, 0.283900f,
    0.348280f, 0.336200f, 0.290800f, 0.195360f, 0.095640f, 0.032010f,
    0.004900f, 0.009300f, 0.063270f, 0.165500f, 0.290400f, 0.433450f,
    0.594500f, 0.762100f, 0.916300f, 1.026300f, 1.062200f, 1.002600f,
    0.854450f, 0.642400f, 0.447900f, 0.283500f, 0.164900f, 0.087400f,
    0.046770f, 0.022700f, 0.011359f, 0.005790f, 0.002899f, 0.001440f,
};

static const CGFloat CIE_Y[KM_SPECTRAL_BANDS] = {
    0.000039f, 0.000120f, 0.000396f, 0.001210f, 0.004000f, 0.011600f,
    0.023000f, 0.038000f, 0.060000f, 0.090980f, 0.139020f, 0.208020f,
    0.323000f, 0.503000f, 0.710000f, 0.862000f, 0.954000f, 0.994950f,
    0.995000f, 0.952000f, 0.870000f, 0.757000f, 0.631000f, 0.503000f,
    0.381000f, 0.265000f, 0.175000f, 0.107000f, 0.061000f, 0.032000f,
    0.017000f, 0.008210f, 0.004102f, 0.002091f, 0.001047f, 0.000520f,
};

static const CGFloat CIE_Z[KM_SPECTRAL_BANDS] = {
    0.006450f, 0.020050f, 0.067850f, 0.207400f, 0.645600f, 1.385600f,
    1.747060f, 1.772110f, 1.669200f, 1.287640f, 0.812950f, 0.465180f,
    0.272000f, 0.158200f, 0.078250f, 0.042160f, 0.020300f, 0.008750f,
    0.003900f, 0.002100f, 0.001650f, 0.001100f, 0.000800f, 0.000340f,
    0.000190f, 0.000050f, 0.000020f, 0.000000f, 0.000000f, 0.000000f,
    0.000000f, 0.000000f, 0.000000f, 0.000000f, 0.000000f, 0.000000f,
};

// ============================================================
// CIE 标准照明体 D65 — 相对光谱功率分布
// ============================================================
static const CGFloat D65[KM_SPECTRAL_BANDS] = {
    49.9755f, 54.6482f, 82.7549f, 91.4860f, 93.4318f, 86.6823f,
    104.8650f, 117.0080f, 117.8120f, 114.8610f, 115.9230f, 108.8110f,
    109.3540f, 107.8020f, 104.7900f, 107.6890f, 104.4050f, 104.0460f,
    100.0000f, 96.3342f, 95.7880f, 88.6856f, 90.0062f, 89.5991f,
    87.6987f, 83.2886f, 83.6992f, 80.0268f, 80.2127f, 82.2774f,
    78.2842f, 69.7208f, 71.6085f, 74.3636f, 61.6040f, 69.8853f,
};

// 归一化因子: k = 100 / Σ(D65_λ × ȳ_λ)
// 使得完美漫反射体 (R=1) 的 Y = 100
static CGFloat _kNormalize = 0;
static BOOL _kNormalizeComputed = NO;

static inline CGFloat kNormalize(void) {
    if (!_kNormalizeComputed) {
        CGFloat sum = 0;
        for (int i = 0; i < KM_SPECTRAL_BANDS; i++) {
            sum += D65[i] * CIE_Y[i];
        }
        _kNormalize = 100.0f / sum;
        _kNormalizeComputed = YES;
    }
    return _kNormalize;
}

// ============================================================
// KMMixResult 实现
// ============================================================
@implementation KMMixResult

- (UIColor *)displayColor {
    CGFloat r = self.sRGB_R;
    CGFloat g = self.sRGB_G;
    CGFloat b = self.sRGB_B;
    // Clip 到 [0, 1]
    r = r < 0 ? 0 : (r > 1 ? 1 : r);
    g = g < 0 ? 0 : (g > 1 ? 1 : g);
    b = b < 0 ? 0 : (b > 1 ? 1 : b);
    return [UIColor colorWithRed:r green:g blue:b alpha:1.0f];
}

- (NSString *)hexString {
    uint8_t r = (uint8_t)(MAX(0, MIN(1, self.sRGB_R)) * 255.0f);
    uint8_t g = (uint8_t)(MAX(0, MIN(1, self.sRGB_G)) * 255.0f);
    uint8_t b = (uint8_t)(MAX(0, MIN(1, self.sRGB_B)) * 255.0f);
    return [NSString stringWithFormat:@"#%02x%02x%02x", r, g, b];
}

- (NSString *)description {
    return [NSString stringWithFormat:
            @"<KMMixResult: L*=%.1f a*=%.1f b*=%.1f HEX=%@>",
            self.L, self.a, self.b, self.hexString];
}

@end

// ============================================================
// KMEngine 实现
// ============================================================
@implementation KMEngine

#pragma mark - 核心混合

+ (KMMixResult *)mixPigments:(NSArray<KMPigment *> *)pigments
                     weights:(NSArray<NSNumber *> *)weights {

    NSUInteger count = pigments.count;
    NSAssert(count == weights.count, @"色浆和重量数量必须一致");
    NSAssert(count > 0, @"至少需要一种色浆");

    // 计算总重量和浓度
    CGFloat totalWeight = 0;
    for (NSNumber *w in weights) {
        totalWeight += [w floatValue];
    }
    if (totalWeight <= 0) {
        totalWeight = 1; // 防御
    }

    CGFloat concentrations[count];
    for (NSUInteger i = 0; i < count; i++) {
        concentrations[i] = [weights[i] floatValue] / totalWeight;
    }

    // ========== 步骤 1: 混合 K/S ==========
    // (K/S)_mix,λ = Σ(c_i × (K/S)_i,λ)
    CGFloat ksMix[KM_SPECTRAL_BANDS];
    memset(ksMix, 0, sizeof(ksMix));

    for (NSUInteger i = 0; i < count; i++) {
        CGFloat c = concentrations[i];
        const CGFloat *ks = pigments[i].ks;
        for (int lam = 0; lam < KM_SPECTRAL_BANDS; lam++) {
            ksMix[lam] += c * ks[lam];
        }
    }

    // ========== 步骤 2: K/S → 反射率 ==========
    // R_λ = 1 + (K/S)_λ - √((1 + (K/S)_λ)² - 1)
    CGFloat reflectance[KM_SPECTRAL_BANDS];
    for (int lam = 0; lam < KM_SPECTRAL_BANDS; lam++) {
        CGFloat ks = ksMix[lam];
        CGFloat r = 1.0f + ks - sqrtf((1.0f + ks) * (1.0f + ks) - 1.0f);
        reflectance[lam] = r < 0 ? 0 : (r > 1 ? 1 : r);
    }

    // ========== 步骤 3: 反射谱 → XYZ ==========
    // X = k × Σ(R_λ × D65_λ × x̄_λ)
    // Y = k × Σ(R_λ × D65_λ × ȳ_λ)
    // Z = k × Σ(R_λ × D65_λ × z̄_λ)
    CGFloat X = 0, Y = 0, Z = 0;
    CGFloat kn = kNormalize();

    for (int lam = 0; lam < KM_SPECTRAL_BANDS; lam++) {
        CGFloat r = reflectance[lam];
        X += r * D65[lam] * CIE_X[lam];
        Y += r * D65[lam] * CIE_Y[lam];
        Z += r * D65[lam] * CIE_Z[lam];
    }

    X *= kn;
    Y *= kn;
    Z *= kn;

    // ========== 步骤 4: XYZ → CIELAB ==========
    CGFloat L, a, b;
    [self xyzToLab_X:X Y:Y Z:Z L:&L a:&a b:&b];

    // ========== 步骤 5: XYZ → sRGB ==========
    CGFloat sr, sg, sb;
    [self xyzToLinearSRGB_X:X Y:Y Z:Z r:&sr g:&sg b:&sb];
    sr = [self linearToSRGB:sr];
    sg = [self linearToSRGB:sg];
    sb = [self linearToSRGB:sb];

    // ========== 组装结果 ==========
    KMMixResult *result = [[KMMixResult alloc] init];
    memcpy(result.reflectance, reflectance, sizeof(reflectance));
    result.X = X;
    result.Y = Y;
    result.Z = Z;
    result.L = L;
    result.a = a;
    result.b = b;
    result.sRGB_R = sr;
    result.sRGB_G = sg;
    result.sRGB_B = sb;
    return result;
}

#pragma mark - 色彩空间: XYZ ↔ CIELAB

// D65 标准白点
static const CGFloat REF_X = 95.047f;
static const CGFloat REF_Y = 100.000f;
static const CGFloat REF_Z = 108.883f;

+ (void)xyzToLab_X:(CGFloat)X Y:(CGFloat)Y Z:(CGFloat)Z
                 L:(CGFloat *)L a:(CGFloat *)a b:(CGFloat *)b {

    CGFloat fx = [self labF:X / REF_X];
    CGFloat fy = [self labF:Y / REF_Y];
    CGFloat fz = [self labF:Z / REF_Z];

    *L = 116.0f * fy - 16.0f;
    *a = 500.0f * (fx - fy);
    *b = 200.0f * (fy - fz);
}

+ (void)labToXYZ_L:(CGFloat)L a:(CGFloat)a b:(CGFloat)b
                 X:(CGFloat *)X Y:(CGFloat *)Y Z:(CGFloat *)Z {

    CGFloat delta = 6.0f / 29.0f;
    CGFloat fy = (L + 16.0f) / 116.0f;
    CGFloat fx = a / 500.0f + fy;
    CGFloat fz = fy - b / 200.0f;

    *X = REF_X * [self labFInv:fx delta:delta];
    *Y = REF_Y * [self labFInv:fy delta:delta];
    *Z = REF_Z * [self labFInv:fz delta:delta];
}

/// f(t) for CIELAB
+ (CGFloat)labF:(CGFloat)t {
    CGFloat delta = 6.0f / 29.0f;
    if (t > delta * delta * delta) {
        return cbrtf(t);
    } else {
        return t / (3.0f * delta * delta) + 4.0f / 29.0f;
    }
}

/// f⁻¹(t) for CIELAB
+ (CGFloat)labFInv:(CGFloat)t delta:(CGFloat)delta {
    if (t > delta) {
        return t * t * t;
    } else {
        return 3.0f * delta * delta * (t - 4.0f / 29.0f);
    }
}

#pragma mark - 色彩空间: XYZ ↔ sRGB

// sRGB 原色矩阵 (D65 白点归一化到 Y=100 时)
+ (void)xyzToLinearSRGB_X:(CGFloat)X Y:(CGFloat)Y Z:(CGFloat)Z
                        r:(CGFloat *)r g:(CGFloat *)g b:(CGFloat *)b {

    CGFloat x = X / 100.0f;
    CGFloat y = Y / 100.0f;
    CGFloat z = Z / 100.0f;

    *r =  3.2404542f * x - 1.5371385f * y - 0.4985314f * z;
    *g = -0.9692660f * x + 1.8760108f * y + 0.0415560f * z;
    *b =  0.0556434f * x - 0.2040259f * y + 1.0572252f * z;
}

+ (CGFloat)linearToSRGB:(CGFloat)c {
    if (c <= 0.0031308f) {
        return 12.92f * c;
    } else {
        return 1.055f * powf(c, 1.0f / 2.4f) - 0.055f;
    }
}

+ (CGFloat)sRGBToLinear:(CGFloat)c {
    if (c <= 0.04045f) {
        return c / 12.92f;
    } else {
        return powf((c + 0.055f) / 1.055f, 2.4f);
    }
}

+ (void)xyzToSRGB_X:(CGFloat)X Y:(CGFloat)Y Z:(CGFloat)Z
                  r:(uint8_t *)r g:(uint8_t *)g b:(uint8_t *)b {

    CGFloat rLin, gLin, bLin;
    [self xyzToLinearSRGB_X:X Y:Y Z:Z r:&rLin g:&gLin b:&bLin];

    CGFloat sr = [self linearToSRGB:rLin];
    CGFloat sg = [self linearToSRGB:gLin];
    CGFloat sb = [self linearToSRGB:bLin];

    *r = (uint8_t)(MAX(0, MIN(1, sr)) * 255.0f + 0.5f);
    *g = (uint8_t)(MAX(0, MIN(1, sg)) * 255.0f + 0.5f);
    *b = (uint8_t)(MAX(0, MIN(1, sb)) * 255.0f + 0.5f);
}

+ (void)sRGBToXYZ_R:(uint8_t)r g:(uint8_t)g b:(uint8_t)b
                  X:(CGFloat *)X Y:(CGFloat *)Y Z:(CGFloat *)Z {

    CGFloat rLin = [self sRGBToLinear:r / 255.0f];
    CGFloat gLin = [self sRGBToLinear:g / 255.0f];
    CGFloat bLin = [self sRGBToLinear:b / 255.0f];

    // Linear RGB → XYZ (Y 范围 0-100)
    *X = 100.0f * (0.4124564f * rLin + 0.3575761f * gLin + 0.1804375f * bLin);
    *Y = 100.0f * (0.2126729f * rLin + 0.7151522f * gLin + 0.0721750f * bLin);
    *Z = 100.0f * (0.0193339f * rLin + 0.1191920f * gLin + 0.9503041f * bLin);
}

#pragma mark - UIColor 便捷转换

+ (void)colorToLab:(UIColor *)color L:(CGFloat *)L a:(CGFloat *)a b:(CGFloat *)b {
    CGFloat r, g, bl, al;
    [color getRed:&r green:&g blue:&bl alpha:&al];

    uint8_t ri = (uint8_t)(r * 255.0f);
    uint8_t gi = (uint8_t)(g * 255.0f);
    uint8_t bi = (uint8_t)(bl * 255.0f);

    CGFloat X, Y, Z;
    [self sRGBToXYZ_R:ri g:gi b:bi X:&X Y:&Y Z:&Z];
    [self xyzToLab_X:X Y:Y Z:Z L:L a:a b:b];
}

+ (void)sRGBToLabR:(uint8_t)r g:(uint8_t)g b:(uint8_t)b
                 L:(CGFloat *)L a:(CGFloat *)a b:(CGFloat *)b {
    CGFloat X, Y, Z;
    [self sRGBToXYZ_R:r g:g b:b X:&X Y:&Y Z:&Z];
    [self xyzToLab_X:X Y:Y Z:Z L:L a:a b:b];
}

#pragma mark - CIEDE2000 色差 (ISO/CIE 11664-6:2014)

#define DEG2RAD(d) ((d) * (CGFloat)M_PI / 180.0f)
#define RAD2DEG(r) ((r) * 180.0f / (CGFloat)M_PI)

+ (CGFloat)deltaE2000_L1:(CGFloat)L1 a1:(CGFloat)a1 b1:(CGFloat)b1
                      L2:(CGFloat)L2 a2:(CGFloat)a2 b2:(CGFloat)b2 {

    // 1. C', h'
    CGFloat C1 = sqrtf(a1 * a1 + b1 * b1);
    CGFloat C2 = sqrtf(a2 * a2 + b2 * b2);
    CGFloat C_avg = (C1 + C2) / 2.0f;

    // 2. G
    CGFloat C_avg_7 = C_avg * C_avg;
    C_avg_7 = C_avg_7 * C_avg_7 * C_avg_7 * C_avg; // C_avg^7
    CGFloat G = 0.5f * (1.0f - sqrtf(C_avg_7 / (C_avg_7 + 6103515625.0f)));
    // 25^7 = 6103515625

    // 3. a'
    CGFloat a1p = (1.0f + G) * a1;
    CGFloat a2p = (1.0f + G) * a2;

    // 4. C', h'
    CGFloat C1p = sqrtf(a1p * a1p + b1 * b1);
    CGFloat C2p = sqrtf(a2p * a2p + b2 * b2);

    CGFloat h1p = atan2f(b1, a1p);
    if (h1p < 0) h1p += 2.0f * (CGFloat)M_PI;
    CGFloat h2p = atan2f(b2, a2p);
    if (h2p < 0) h2p += 2.0f * (CGFloat)M_PI;

    // 5. ΔL', ΔC', ΔH'
    CGFloat dLp = L2 - L1;
    CGFloat dCp = C2p - C1p;

    CGFloat dhp;
    if (C1p * C2p == 0) {
        dhp = 0;
    } else {
        CGFloat diff = h2p - h1p;
        if (fabsf(diff) <= (CGFloat)M_PI) {
            dhp = diff;
        } else if (diff > (CGFloat)M_PI) {
            dhp = diff - 2.0f * (CGFloat)M_PI;
        } else {
            dhp = diff + 2.0f * (CGFloat)M_PI;
        }
    }
    CGFloat dHp = 2.0f * sqrtf(C1p * C2p) * sinf(dhp / 2.0f);

    // 6. 均值
    CGFloat L_avg = (L1 + L2) / 2.0f;
    CGFloat Cp_avg = (C1p + C2p) / 2.0f;

    CGFloat hp_avg;
    if (C1p * C2p == 0) {
        hp_avg = h1p + h2p;
    } else {
        if (fabsf(h1p - h2p) <= (CGFloat)M_PI) {
            hp_avg = (h1p + h2p) / 2.0f;
        } else if (h1p + h2p < 2.0f * (CGFloat)M_PI) {
            hp_avg = (h1p + h2p + 2.0f * (CGFloat)M_PI) / 2.0f;
        } else {
            hp_avg = (h1p + h2p - 2.0f * (CGFloat)M_PI) / 2.0f;
        }
    }

    // 7. T
    CGFloat hp_avg_deg = hp_avg * 180.0f / (CGFloat)M_PI;
    CGFloat T = (1.0f
                 - 0.17f * cosf(DEG2RAD(hp_avg_deg - 30.0f))
                 + 0.24f * cosf(DEG2RAD(2.0f * hp_avg_deg))
                 + 0.32f * cosf(DEG2RAD(3.0f * hp_avg_deg + 6.0f))
                 - 0.20f * cosf(DEG2RAD(4.0f * hp_avg_deg - 63.0f)));

    // 8. S_L, S_C, S_H
    CGFloat S_L = 1.0f + (0.015f * (L_avg - 50.0f) * (L_avg - 50.0f))
                          / sqrtf(20.0f + (L_avg - 50.0f) * (L_avg - 50.0f));
    CGFloat S_C = 1.0f + 0.045f * Cp_avg;
    CGFloat S_H = 1.0f + 0.015f * Cp_avg * T;

    // 9. R_T
    CGFloat dTheta = 30.0f * expf(-powf((hp_avg_deg - 275.0f) / 25.0f, 2));
    CGFloat Cp_avg_7 = Cp_avg * Cp_avg;
    Cp_avg_7 = Cp_avg_7 * Cp_avg_7 * Cp_avg_7 * Cp_avg;
    CGFloat R_C = 2.0f * sqrtf(Cp_avg_7 / (Cp_avg_7 + 6103515625.0f));
    CGFloat R_T = -R_C * sinf(DEG2RAD(2.0f * dTheta));

    // 10. ΔE00
    CGFloat kL = 1.0f, kC = 1.0f, kH = 1.0f;

    CGFloat term1 = dLp / (kL * S_L);
    CGFloat term2 = dCp / (kC * S_C);
    CGFloat term3 = dHp / (kH * S_H);

    return sqrtf(term1 * term1 + term2 * term2 + term3 * term3
                  + R_T * term2 * term3);
}

#pragma mark - 便捷色差计算

+ (CGFloat)deltaEFromTargetColor:(UIColor *)targetColor
                       mixResult:(KMMixResult *)mixResult {
    CGFloat Lt, at, bt;
    [self colorToLab:targetColor L:&Lt a:&at b:&bt];
    return [self deltaE2000_L1:Lt a1:at b1:bt
                            L2:mixResult.L a2:mixResult.a b2:mixResult.b];
}

#pragma mark - 单值 K/S ↔ 反射率

+ (CGFloat)reflectanceFromKS:(CGFloat)ks {
    return 1.0f + ks - sqrtf((1.0f + ks) * (1.0f + ks) - 1.0f);
}

+ (CGFloat)ksFromReflectance:(CGFloat)r {
    if (r < 0.001f) r = 0.001f;
    if (r > 0.999f) r = 0.999f;
    return (1.0f - r) * (1.0f - r) / (2.0f * r);
}

@end
