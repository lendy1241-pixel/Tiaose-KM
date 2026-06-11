//
//  KMPigmentDatabase.m — 预设色浆库实现
//  每种色浆从反射率曲线反算 K/S 数据
//

#import "KMPigmentDatabase.h"
#import "KMEngine.h"

// ============================================================
// 辅助: 从关键波长线性插值生成 36 点反射率
// ============================================================
static void buildReflectance(NSArray<NSNumber *> *keyWL, NSArray<NSNumber *> *keyRef,
                              CGFloat *outRefl) {
    NSInteger nKeys = keyWL.count;
    CGFloat *kwls = malloc(sizeof(CGFloat) * nKeys);
    CGFloat *krefs = malloc(sizeof(CGFloat) * nKeys);
    for (NSInteger i = 0; i < nKeys; i++) {
        kwls[i] = [keyWL[i] floatValue];
        krefs[i] = [keyRef[i] floatValue];
    }

    for (int i = 0; i < KM_SPECTRAL_BANDS; i++) {
        NSInteger wl = KMWavelengthAtIndex(i);

        if (wl <= kwls[0]) {
            outRefl[i] = krefs[0];
        } else if (wl >= kwls[nKeys - 1]) {
            outRefl[i] = krefs[nKeys - 1];
        } else {
            for (NSInteger j = 0; j < nKeys - 1; j++) {
                if (kwls[j] <= wl && wl <= kwls[j + 1]) {
                    CGFloat t = (CGFloat)(wl - kwls[j]) / (kwls[j + 1] - kwls[j]);
                    outRefl[i] = krefs[j] + t * (krefs[j + 1] - krefs[j]);
                    break;
                }
            }
        }
    }
    free(kwls);
    free(krefs);
}

// ============================================================
// 色浆定义 — 反射率关键点
// ============================================================

typedef struct {
    NSString *name;
    NSString *desc;
    NSInteger nWL;
    CGFloat keyWL[10];
    CGFloat keyRef[10];
} PigmentDef;

static PigmentDef _defs[] = {
    {
        @"钛白", @"Titanium White — 高散射、低吸收，调色基础白",
        3,
        {380, 420, 730},
        {0.92, 0.95, 0.96},
    },
    {
        @"炭黑", @"Carbon Black — 全波段高吸收",
        2,
        {380, 730},
        {0.025, 0.025},
    },
    {
        @"铁红", @"Red Iron Oxide (PR101) — 暖红，蓝绿波段强吸收",
        7,
        {380, 430, 500, 550, 580, 620, 730},
        {0.030, 0.025, 0.018, 0.020, 0.120, 0.450, 0.720},
    },
    {
        @"酞青蓝", @"Phthalo Blue (PB15:3) — 红/黄波段强吸收，蓝波段高反射",
        7,
        {380, 440, 470, 500, 550, 620, 730},
        {0.040, 0.080, 0.380, 0.180, 0.030, 0.015, 0.010},
    },
    {
        @"铬黄", @"Chrome Yellow (PY34) — 蓝波段吸收，黄-红波段高反射",
        7,
        {380, 440, 480, 520, 570, 620, 730},
        {0.025, 0.025, 0.060, 0.350, 0.750, 0.850, 0.870},
    },
    {
        @"酞青绿", @"Phthalo Green (PG7) — 红/蓝波段吸收，绿波段高反射",
        7,
        {380, 440, 480, 520, 550, 620, 730},
        {0.015, 0.030, 0.060, 0.420, 0.350, 0.020, 0.010},
    },
    {
        @"永固红", @"Permanent Red (PR170) — 比铁红更鲜艳，偏橙",
        7,
        {380, 430, 500, 550, 580, 620, 730},
        {0.030, 0.025, 0.015, 0.020, 0.250, 0.650, 0.780},
    },
    {
        @"群青", @"Ultramarine Blue (PB29) — 暖蓝色，紫波段高反射",
        7,
        {380, 420, 450, 480, 520, 600, 730},
        {0.060, 0.120, 0.300, 0.220, 0.050, 0.020, 0.015},
    },
};
static const NSInteger _defCount = sizeof(_defs) / sizeof(PigmentDef);

// ============================================================
// 缓存
// ============================================================
static NSMutableDictionary<NSString *, KMPigment *> *_cache = nil;

@implementation KMPigmentDatabase

+ (void)initialize {
    if (self == [KMPigmentDatabase class]) {
        _cache = [NSMutableDictionary dictionary];
    }
}

+ (NSArray<NSString *> *)allPigmentNames {
    NSMutableArray *names = [NSMutableArray arrayWithCapacity:_defCount];
    for (NSInteger i = 0; i < _defCount; i++) {
        [names addObject:_defs[i].name];
    }
    return names;
}

+ (KMPigment *)pigmentWithName:(NSString *)name {
    // 检查缓存
    KMPigment *cached = _cache[name];
    if (cached) return cached;

    // 查找定义
    for (NSInteger i = 0; i < _defCount; i++) {
        if ([_defs[i].name isEqualToString:name]) {
            PigmentDef *def = &_defs[i];

            // 构建反射率曲线
            CGFloat reflectance[KM_SPECTRAL_BANDS];

            // 组装 NSArray
            NSMutableArray *kWl = [NSMutableArray arrayWithCapacity:def->nWL];
            NSMutableArray *kRef = [NSMutableArray arrayWithCapacity:def->nWL];
            for (NSInteger j = 0; j < def->nWL; j++) {
                [kWl addObject:@(def->keyWL[j])];
                [kRef addObject:@(def->keyRef[j])];
            }
            buildReflectance(kWl, kRef, reflectance);

            // 反射率 → K/S
            CGFloat ks[KM_SPECTRAL_BANDS];
            [KMPigment reflectanceToKS:reflectance ksOutput:ks count:KM_SPECTRAL_BANDS];

            // 创建色浆
            KMPigment *pigment = [[KMPigment alloc] initWithName:name ksValues:ks];
            _cache[name] = pigment;
            return pigment;
        }
    }
    return nil;
}

+ (NSArray<KMPigment *> *)allPigments {
    NSMutableArray *pigments = [NSMutableArray arrayWithCapacity:_defCount];
    for (NSInteger i = 0; i < _defCount; i++) {
        [pigments addObject:[self pigmentWithName:_defs[i].name]];
    }
    return pigments;
}

+ (NSString *)descriptionForPigment:(NSString *)name {
    for (NSInteger i = 0; i < _defCount; i++) {
        if ([_defs[i].name isEqualToString:name]) {
            return _defs[i].desc;
        }
    }
    return nil;
}

+ (KMPigment *)pigmentWithName:(NSString *)name
                 keyWavelengths:(NSArray<NSNumber *> *)keyWavelengths
               keyReflectances:(NSArray<NSNumber *> *)keyReflectances {

    CGFloat reflectance[KM_SPECTRAL_BANDS];
    buildReflectance(keyWavelengths, keyReflectances, reflectance);

    CGFloat ks[KM_SPECTRAL_BANDS];
    [KMPigment reflectanceToKS:reflectance ksOutput:ks count:KM_SPECTRAL_BANDS];

    return [[KMPigment alloc] initWithName:name ksValues:ks];
}

@end
