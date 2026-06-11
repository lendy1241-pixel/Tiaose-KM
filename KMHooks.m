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
// dlsym 安全查找宏
// ============================================================
#define KM_OBJC(type, name)  ((__bridge type)dlsym(RTLD_DEFAULT, #name))
#define KM_PTR(type, name)   ((type)dlsym(RTLD_DEFAULT, #name))

// ============================================================
// 旧的 IMP 保存
// ============================================================
static void (*original_checkTapped)(id, SEL, id) = NULL;
static id   (*original_mixColor)(id, SEL) = NULL;
static BOOL _hooksInstalled = NO;


// ============================================================
// 新的 mixColor
// ============================================================
static UIColor *km_mixColor(id self, SEL _cmd) {
    NSMutableArray *gNames   = KM_OBJC(NSMutableArray *, _gNames);
    NSMutableArray *gAmounts = KM_OBJC(NSMutableArray *, _gAmounts);
    NSMutableArray *gFields  = KM_OBJC(NSMutableArray *, _gFields);

    NSMutableArray<KMPigment *> *pigments = [NSMutableArray array];
    NSMutableArray<NSNumber *> *weights = [NSMutableArray array];

    NSUInteger count = gNames ? gNames.count : 0;
    for (NSUInteger i = 0; i < count; i++) {
        CGFloat w = 0;
        if (gAmounts && i < gAmounts.count) {
            id amountObj = gAmounts[i];
            if ([amountObj isKindOfClass:[NSNumber class]])
                w = [(NSNumber *)amountObj floatValue];
            else if ([amountObj isKindOfClass:[NSString class]])
                w = [(NSString *)amountObj floatValue];
        }
        if (w <= 0.001 && gFields && i < gFields.count) {
            id field = gFields[i];
            if ([field respondsToSelector:@selector(text)])
                w = [[field performSelector:@selector(text)] floatValue];
        }
        if (w <= 0.001) continue;

        NSString *name = nil;
        if (gNames && i < gNames.count) {
            id nameObj = gNames[i];
            if ([nameObj isKindOfClass:[NSString class]]) name = nameObj;
        }
        if (!name) name = [NSString stringWithFormat:@"P%lu", (unsigned long)i];

        KMPigment *pigment = [KMPigmentDatabase pigmentWithName:name];
        if (pigment) {
            [pigments addObject:pigment];
            [weights addObject:@(w)];
        }
    }

    if (pigments.count == 0) {
        if (original_mixColor) return original_mixColor(self, _cmd);
        return [UIColor grayColor];
    }

    KMMixResult *result = [KMEngine mixPigments:pigments weights:weights];
    return result.displayColor;
}


// ============================================================
// 新的 checkTapped:
// ============================================================
static void km_checkTapped(id self, SEL _cmd, id sender) {
    UIView *gTargetView   = KM_OBJC(UIView *, _gTargetView);
    UIView *gCurrentView  = KM_OBJC(UIView *, _gCurrentView);
    UILabel *gStatusLabel = KM_OBJC(UILabel *, _gStatusLabel);
    NSMutableArray *gHist = KM_OBJC(NSMutableArray *, _gHistory);
    CGFloat *gBestDiff    = KM_PTR(CGFloat *, _gBestDifference);

    UIColor *mixedColor = km_mixColor(self, @selector(mixColor));

    UIColor *targetColor = nil;
    if (gTargetView) targetColor = gTargetView.backgroundColor;
    if (!targetColor || targetColor == [UIColor clearColor])
        targetColor = [UIColor whiteColor];

    if (gCurrentView) gCurrentView.backgroundColor = mixedColor;

    CGFloat tL, ta, tb, mL, ma, mb;
    [KMEngine colorToLab:targetColor L:&tL a:&ta b:&tb];
    [KMEngine colorToLab:mixedColor L:&mL a:&ma b:&mb];
    CGFloat diff = [KMEngine deltaE2000_L1:tL a1:ta b1:tb L2:mL a2:ma b2:mb];

    if (gStatusLabel) {
        NSString *grade;
        if (diff < 1.0)       grade = @"Perfect!";
        else if (diff < 3.0)  grade = @"Excellent";
        else if (diff < 6.0)  grade = @"Good";
        else if (diff < 12.0) grade = @"Fair";
        else                  grade = @"Try again";

        gStatusLabel.text = [NSString stringWithFormat:
            @"dE00=%.2f %@\nL*=%.0f a*=%.1f b*=%.1f",
            diff, grade, mL, ma, mb];
    }

    if (gBestDiff) {
        if (diff < *gBestDiff || *gBestDiff == 0)
            *gBestDiff = diff;
    }

    if (gHist && mixedColor && targetColor) {
        [gHist addObject:@{
            @"target": targetColor,
            @"mixed": mixedColor,
            @"deltaE": @(diff),
            @"timestamp": [NSDate date],
        }];
    }
}


// ============================================================
// KMHooks
// ============================================================
@interface KMHooks : NSObject
+ (void)install;
@end

@implementation KMHooks

+ (void)install {
    if (_hooksInstalled) return;

    Class mixVC = NSClassFromString(@"MixViewController");
    if (!mixVC) {
        NSLog(@"[KMEngine] MixViewController not found, hooks skipped");
        return;
    }

    NSLog(@"[KMEngine] Installing hooks on %@", mixVC);

    SEL mixSel = NSSelectorFromString(@"mixColor");
    Method mixMethod = class_getInstanceMethod(mixVC, mixSel);
    if (mixMethod) {
        original_mixColor = (id(*)(id, SEL))method_getImplementation(mixMethod);
        method_setImplementation(mixMethod, (IMP)km_mixColor);
        NSLog(@"[KMEngine] mixColor -> KM");
    } else {
        class_addMethod(mixVC, mixSel, (IMP)km_mixColor, "@@:");
        NSLog(@"[KMEngine] mixColor added");
    }

    SEL checkSel = NSSelectorFromString(@"checkTapped:");
    Method checkMethod = class_getInstanceMethod(mixVC, checkSel);
    if (checkMethod) {
        original_checkTapped = (void(*)(id, SEL, id))method_getImplementation(checkMethod);
        method_setImplementation(checkMethod, (IMP)km_checkTapped);
        NSLog(@"[KMEngine] checkTapped: -> KM+CIEDE2000");
    }

    _hooksInstalled = YES;
    NSLog(@"[KMEngine] Hooks ready. pigments: %@", [KMPigmentDatabase allPigmentNames]);
}

@end


// ============================================================
// 自动安装
// ============================================================
__attribute__((constructor))
static void KMHooksInit(void) {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        [KMHooks install];
    });
}
