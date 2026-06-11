//
//  KMPigment.m — 色浆光谱数据模型实现
//

#import "KMPigment.h"

@implementation KMPigment

- (instancetype)initWithName:(NSString *)name ksValues:(const CGFloat *)ksValues {
    self = [super init];
    if (self) {
        _name = [name copy];
        if (ksValues) {
            memcpy(_ks.values, ksValues, sizeof(CGFloat) * KM_SPECTRAL_BANDS);
        } else {
            memset(_ks.values, 0, sizeof(CGFloat) * KM_SPECTRAL_BANDS);
        }
    }
    return self;
}

+ (void)reflectanceToKS:(const CGFloat *)reflectance
              ksOutput:(CGFloat *)ksOutput
                 count:(NSInteger)count {
    for (NSInteger i = 0; i < count; i++) {
        CGFloat r = reflectance[i];
        // 限制范围避免除零
        if (r < 0.001) r = 0.001;
        if (r > 0.999) r = 0.999;
        ksOutput[i] = (1.0f - r) * (1.0f - r) / (2.0f * r);
    }
}

- (CGFloat)ksAtWavelength:(NSInteger)wavelength {
    return self.ks.values[KMIndexAtWavelength(wavelength)];
}

- (NSString *)description {
    return [NSString stringWithFormat:@"<KMPigment: %@>", self.name];
}

@end
