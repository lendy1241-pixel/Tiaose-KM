//
//  KMPigmentDatabase.h — 预设色浆库
//  8 种常用色浆的 K/S 光谱数据
//

#import <Foundation/Foundation.h>
#import "KMPigment.h"

@interface KMPigmentDatabase : NSObject

/// 所有预设色浆名称
+ (NSArray<NSString *> *)allPigmentNames;

/// 通过名称获取色浆 (钛白, 炭黑, 铁红, 酞青蓝, 铬黄, 酞青绿, 永固红, 群青)
+ (KMPigment *)pigmentWithName:(NSString *)name;

/// 获取所有色浆
+ (NSArray<KMPigment *> *)allPigments;

/// 获取色浆描述
+ (NSString *)descriptionForPigment:(NSString *)name;

/// 从反射率关键点创建自定义色浆
/// @param name 名称
/// @param keyWavelengths 关键波长数组 (如 @[@380, @500, @730])
/// @param keyReflectances 对应反射率 (0-1)
+ (KMPigment *)pigmentWithName:(NSString *)name
                 keyWavelengths:(NSArray<NSNumber *> *)keyWavelengths
               keyReflectances:(NSArray<NSNumber *> *)keyReflectances;

@end
