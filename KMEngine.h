//
//  KMEngine.h — Kubelka-Munk 色浆混合引擎
//  核心算法: KM 单常数模型 → 反射谱 → XYZ → sRGB + CIELAB → ΔE2000
//

#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import "KMPigment.h"

/// 混合结果
@interface KMMixResult : NSObject

/// 反射率曲线 (36 点, 380-730nm, 步长 10nm)
@property (nonatomic, assign) KMSpectralCurve reflectance;

/// CIE XYZ 三刺激值 (D65, Y=100 白点)
@property (nonatomic, assign) CGFloat X;
@property (nonatomic, assign) CGFloat Y;
@property (nonatomic, assign) CGFloat Z;

/// CIELAB L*a*b* 值
@property (nonatomic, assign) CGFloat L;
@property (nonatomic, assign) CGFloat a;
@property (nonatomic, assign) CGFloat b;

/// sRGB 分量 (可能超出 0-1 范围, 伽马校正后)
@property (nonatomic, assign) CGFloat sRGB_R;
@property (nonatomic, assign) CGFloat sRGB_G;
@property (nonatomic, assign) CGFloat sRGB_B;

/// 显示用 UIColor (自动 clip 到 [0,1])
@property (nonatomic, strong, readonly) UIColor *displayColor;

/// 十六进制颜色字符串 (如 "#feaca1")
@property (nonatomic, copy, readonly) NSString *hexString;

@end


/// Kubelka-Munk 混合引擎
@interface KMEngine : NSObject

#pragma mark - 核心混合

/// 混合多种色浆
/// @param pigments 色浆数组 (KMPigment *)
/// @param weights  对应重量 (NSNumber *, 克), 与 pigments 长度相同
/// @return 包含反射谱、LAB、sRGB 等完整信息的混合结果
+ (KMMixResult *)mixPigments:(NSArray<KMPigment *> *)pigments
                     weights:(NSArray<NSNumber *> *)weights;

#pragma mark - 色彩空间转换

/// UIColor → CIELAB (D65)
+ (void)colorToLab:(UIColor *)color L:(CGFloat *)L a:(CGFloat *)a b:(CGFloat *)b;

/// sRGB (0-255) → CIELAB
+ (void)sRGBToLabR:(uint8_t)r g:(uint8_t)g b:(uint8_t)b
                 L:(CGFloat *)L a:(CGFloat *)a b:(CGFloat *)outB;

/// CIELAB → XYZ (D65)
+ (void)labToXYZ_L:(CGFloat)L a:(CGFloat)a b:(CGFloat)b
                 X:(CGFloat *)X Y:(CGFloat *)Y Z:(CGFloat *)Z;

/// XYZ (D65) → sRGB (0-255)
+ (void)xyzToSRGB_X:(CGFloat)X Y:(CGFloat)Y Z:(CGFloat)Z
                  r:(uint8_t *)r g:(uint8_t *)g b:(uint8_t *)b;

/// sRGB (0-255) → XYZ (D65)
+ (void)sRGBToXYZ_R:(uint8_t)r g:(uint8_t)g b:(uint8_t)b
                  X:(CGFloat *)X Y:(CGFloat *)Y Z:(CGFloat *)Z;

#pragma mark - 色差计算

/// CIEDE2000 色差 (ΔE00)
/// 最精确的色差公式，考虑人眼对不同色区的敏感度差异
/// < 1.0 → 肉眼难以分辨
/// < 3.0 → 一般工业可接受
/// < 6.0 → 可察觉但可接受
+ (CGFloat)deltaE2000_L1:(CGFloat)L1 a1:(CGFloat)a1 b1:(CGFloat)b1
                      L2:(CGFloat)L2 a2:(CGFloat)a2 b2:(CGFloat)b2;

/// 计算 KMMixResult 与目标 UIColor 之间的 ΔE2000
+ (CGFloat)deltaEFromTargetColor:(UIColor *)targetColor
                       mixResult:(KMMixResult *)mixResult;

/// K/S → 反射率 (KM 逆公式)
+ (CGFloat)reflectanceFromKS:(CGFloat)ks;

/// 反射率 → K/S
+ (CGFloat)ksFromReflectance:(CGFloat)r;

@end
