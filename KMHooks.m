//
//  KMHooks.m — 方法交换入口
//  安全版: 使用 dlsym 查找外部符号，找不到就优雅降级
//

#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <dlfcn.h>
#import "KMEngine.h"
#import "KMPigmentDatabase.h"

// ============================================================
// 宏: 从主二进制安全查找全局变量 (dlsym)
// ============================================================
#define KM_LOOKUP(type, name) ((type)dlsym(RTLD_DEFAULT, #name))

// ============================================================
// 旧的 IMP 保存
// ============================================================
static void (*original_checkTapped)(id, SEL, id) = NULL;
static id   (*original_mixColor)(id, SEL) = NULL;

// 是否成功安装了 hooks
static BOOL _hooksInstalled = NO;


// ============================================================
// 新的 mixColor: 用 KM 引擎替代 RGB 加权平均
// ============================================================
static UIColor *km_mixColor(id self, SEL _cmd) {
    // 安全查找全局变量（每次调用时查找，确保 App 已初始化）
    NSMutableArray *gNames   = KM_LOOKUP(NSMutableArray *, _gNames);
    NSMutableArray *gAmounts = KM_LOOKUP(NSMutableArray *, _gAmounts);
    NSMutableArray *gFields  = KM_LOOKUP(NSMutableArray *, _gFields);

    NSMutableArray<KMPigment *> *pigments = [NSMutableArray array];
    NSMutableArray<NSNumber *> *weights = [NSMutableArray array];

    NSUInteger count = gNames ? gNames.count : 0;
    for (NSUInteger i = 0; i < count; i++) {
        CGFloat w = 0;
        if (gAmounts && i < gAmounts.count) {
            id amountObj = gAmounts[i];
            if ([amountObj isKindOfClass:[NSNumber class]]) {
                w = [(NSNumber *)amountObj floatValue];
            } else if ([amountObj isKindOfClass:[NSString class]]) {
                w = [(NSString *)amountObj floatValue];
            }
        }
        if (w <= 0.001 && gFields && i < gFields.count) {
            id field = gFields[i];
            if ([field respondsToSelector:@selector(text)]) {
                w = [[field performSelector:@selector(text)] floatValue];
            }
        }
        if (w <= 0.001) continue;

        NSString *name = nil;
        if (gNames && i < gNames.count) {
            id nameObj = gNames[i];
            if ([nameObj isKindOfClass:[NSString class]]) {
                name = nameObj;
            }
        }
        if (!name) name = [NSString stringWithFormat:@"色浆%lu", (unsigned long)i];

        KMPigment *pigment = [KMPigmentDatabase pigmentWithName:name];
        if (pigment) {
            [pigments addObject:pigment];
            [weights addObject:@(w)];
        }
    }

    if (pigments.count == 0) {
        // 没有任何已知色浆 → fallback 回原方法
        if (original_mixColor) {
            return original_mixColor(self, _cmd);
        }
        return [UIColor grayColor];
    }

    KMMixResult *result = [KMEngine mixPigments:pigments weights:weights];
    return result.displayColor;
}


// ============================================================
// 新的 checkTapped: 用 KM + CIEDE2000 替代旧的 RGB 对比
// ============================================================
static void km_checkTapped(id self, SEL _cmd, id sender) {
    // 安全查找
    UIView *gTargetView  = KM_LOOKUP(UIView *, _gTargetView);
    UIView *gCurrentView = KM_LOOKUP(UIView *, _gCurrentView);
    UILabel *gStatusLabel = KM_LOOKUP(UILabel *, _gStatusLabel);
    NSMutableArray *gHistory = KM_LOOKUP(NSMutableArray *, _gHistory);
    CGFloat *gBestDifference = KM_LOOKUP(CGFloat *, _gBestDifference);

    // --- 1. KM 混合 ---
    UIColor *mixedColor = km_mixColor(self, @selector(mixColor));

    // --- 2. 获取目标色 ---
    UIColor *targetColor = nil;
    if (gTargetView) {
        targetColor = gTargetView.backgroundColor;
    }
    if (!targetColor || targetColor == [UIColor clearColor]) {
        targetColor = [UIColor whiteColor];
    }

    // --- 3. 更新当前色显示 ---
    if (gCurrentView) {
        gCurrentView.backgroundColor = mixedColor;
    }

    // --- 4. CIEDE2000 色差 ---
    CGFloat tL, ta, tb;
    [KMEngine colorToLab:targetColor L:&tL a:&ta b:&tb];

    CGFloat mL, ma, mb;
    [KMEngine colorToLab:mixedColor L:&mL a:&ma b:&mb];

    CGFloat diff = [KMEngine deltaE2000_L1:tL a1:ta b1:tb L2:mL a2:ma b2:mb];

    // --- 5. 更新状态标签 ---
    if (gStatusLabel) {
        NSString *grade;
        if (diff < 1.0)       grade = @"🏆 完美!";
        else if (diff < 3.0)  grade = @"✅ 优秀";
        else if (diff < 6.0)  grade = @"👍 良好";
        else if (diff < 12.0) grade = @"⚠️ 一般";
        else                  grade = @"❌ 再试试";

        gStatusLabel.text = [NSString stringWithFormat:
            @"ΔE00=%.2f %@\nL*=%.0f a*=%.1f b*=%.1f",
            diff, grade, mL, ma, mb];
    }

    // --- 6. 更新最佳记录 ---
    if (gBestDifference) {
        if (diff < *gBestDifference || *gBestDifference == 0) {
            *gBestDifference = diff;
        }
    }

    // --- 7. 保存历史 ---
    if (gHistory && mixedColor && targetColor) {
        NSDictionary *entry = @{
            @"target": targetColor,
            @"mixed": mixedColor,
            @"deltaE": @(diff),
            @"timestamp": [NSDate date],
        };
        [gHistory addObject:entry];
    }
}


// ============================================================
// KMHooks 类 — 负责安装方法交换
// ============================================================
@interface KMHooks : NSObject
+ (void)install;
@end

@implementation KMHooks

+ (void)install {
    if (_hooksInstalled) return;

    Class mixVC = NSClassFromString(@"MixViewController");
    if (!mixVC) {
        NSLog(@"[KMEngine] MixViewController not found — perhaps app structure changed?");
        NSLog(@"[KMEngine] KM engine loaded but hooks not installed.");
        return;
    }

    NSLog(@"[KMEngine] Installing KM hooks on %@", mixVC);

    // --- 交换 mixColor ---
    SEL mixSel = NSSelectorFromString(@"mixColor");
    Method mixMethod = class_getInstanceMethod(mixVC, mixSel);
    if (mixMethod) {
        original_mixColor = (id(*)(id, SEL))method_getImplementation(mixMethod);
        method_setImplementation(mixMethod, (IMP)km_mixColor);
        NSLog(@"[KMEngine] ✓ mixColor -> KM engine");
    } else {
        class_addMethod(mixVC, mixSel, (IMP)km_mixColor, "@@:");
        NSLog(@"[KMEngine] ✓ mixColor added (was missing)");
    }

    // --- 交换 checkTapped: ---
    SEL checkSel = NSSelectorFromString(@"checkTapped:");
    Method checkMethod = class_getInstanceMethod(mixVC, checkSel);
    if (checkMethod) {
        original_checkTapped = (void(*)(id, SEL, id))method_getImplementation(checkMethod);
        method_setImplementation(checkMethod, (IMP)km_checkTapped);
        NSLog(@"[KMEngine] ✓ checkTapped: -> KM + CIEDE2000");
    }

    _hooksInstalled = YES;
    NSLog(@"[KMEngine] All hooks installed. 预设色浆: %@",
          [KMPigmentDatabase allPigmentNames]);
}

@end


// ============================================================
// 自动安装入口: dylib 加载时延迟安装 hooks
// ============================================================
__attribute__((constructor))
static void KMHooksInit(void) {
    // 延迟确保 App 已完全启动
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        [KMHooks install];
    });
}
