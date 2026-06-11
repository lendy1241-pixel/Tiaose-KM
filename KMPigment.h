//
//  KMPigment.h — 色浆光谱数据模型
//  每种色浆持有 36 个波段的 K/S (吸收/散射比) 数据
//

#import <Foundation/Foundation.h>

// 光谱参数: 380nm - 730nm, 10nm 步长
#define KM_SPECTRAL_BANDS 36
#define KM_WAVELENGTH_START 380
#define KM_WAVELENGTH_STEP 10

/// 获取波段索引对应的波长 (nm)
static inline NSInteger KMWavelengthAtIndex(NSInteger index) {
    return KM_WAVELENGTH_START + index * KM_WAVELENGTH_STEP;
}

/// 获取波长对应的波段索引 (返回最接近的)
static inline NSInteger KMIndexAtWavelength(NSInteger wavelength) {
    NSInteger idx = (wavelength - KM_WAVELENGTH_START) / KM_WAVELENGTH_STEP;
    if (idx < 0) idx = 0;
    if (idx >= KM_SPECTRAL_BANDS) idx = KM_SPECTRAL_BANDS - 1;
    return idx;
}

/// 光谱数据曲线 (用于 @property 中承载 C 数组)
/// 用法: curve.values[i] 访问第 i 个波段
typedef struct {
    CGFloat values[KM_SPECTRAL_BANDS];
} KMSpectralCurve;

@interface KMPigment : NSObject

/// 色浆名称 (如 "钛白", "铁红")
@property (nonatomic, copy) NSString *name;

/// K/S 值数组 [KM_SPECTRAL_BANDS]
/// ks.values[0] = 380nm, ks.values[35] = 730nm
/// K/S 越高 → 该波段吸收越强 → 颜色越暗
/// K/S 越低 → 该波段散射越强 → 颜色越亮
@property (nonatomic, assign) KMSpectralCurve ks;

/// 用名称 + K/S 数组初始化
- (instancetype)initWithName:(NSString *)name ksValues:(const CGFloat *)ksValues;

/// 从反射率数组反算 K/S (反射率 0-1)
/// ks = (1-R)² / (2R)
+ (void)reflectanceToKS:(const CGFloat *)reflectance
              ksOutput:(CGFloat *)ksOutput
                 count:(NSInteger)count;

/// 获取指定波长的 K/S 值
- (CGFloat)ksAtWavelength:(NSInteger)wavelength;

@end
