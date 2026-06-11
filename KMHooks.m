//
//  KMHooks.m — 方法交换入口 (+load)
//  在 dylib 被加载时自动替换旧的 RGB 混合方法为 KM 引擎
//

#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import "KMEngine.h"
#import "KMPigmentDatabase.h"

// ============================================================
// 外部全局变量 — 从原版二进制导出
//   (这些符号在原 binary 的 __data 段，dylib 注入后可访问)
// ============================================================

// ---- 色浆数据 ----
extern NSMutableArray   *_gNames;       // 色浆名称 (NSString *)
extern NSMutableArray   *_gAmounts;     // 用量克数 (NSNumber *)
extern NSMutableArray   *_gPigments;    // 旧版色浆颜色 (UIColor *), KM 下不再使用
extern int               _gAddCount;    // 已添加色浆数量

// ---- UI ----
extern UIView           *_gTargetView;   // 目标色显示
extern UIView           *_gCurrentView;  // 当前混合色显示
extern UILabel          *_gStatusLabel;  // 状态/色差标签
extern UILabel          *_gGuideLabel;   // 引导/标题标签
extern UILabel          *_gChallengeTitle; // 挑战标题
extern UILabel          *_gWeightLabel;  // 重量标签
extern UILabel          *_gHistoryLabel; // 历史标签
extern UIScrollView     *_gScroll;       // 滚动视图
extern NSMutableArray   *_gFields;       // 输入框 (UITextField *)

// ---- 评分 & 历史 ----
extern CGFloat           _gBestDifference;   // 最佳 ΔE
extern CGFloat           _gStartDifference;  // 初始 ΔE
extern NSMutableArray   *_gHistory;          // 历史记录

// ---- 任务 ----
extern NSMutableArray   *_gTasks;        // 任务列表
extern int               _gTaskIndex;    // 当前任务索引


// ============================================================
// 旧的 IMP 保存
// ============================================================
static void (*original_checkTapped)(id, SEL, id) = NULL;
static id   (*original_mixColor)(id, SEL) = NULL;


// ============================================================
// 新的 mixColor: 用 KM 引擎替代 RGB 加权平均
// ============================================================
static UIColor *km_mixColor(id self, SEL _cmd) {
    // 收集色浆
    NSMutableArray<KMPigment *> *pigments = [NSMutableArray array];
    NSMutableArray<NSNumber *> *weights = [NSMutableArray array];

    NSUInteger count = _gNames ? _gNames.count : 0;
    for (NSUInteger i = 0; i < count; i++) {
        CGFloat w = 0;
        if (_gAmounts && i < _gAmounts.count) {
            id amountObj = _gAmounts[i];
            if ([amountObj isKindOfClass:[NSNumber class]]) {
                w = [(NSNumber *)amountObj floatValue];
            } else if ([amountObj isKindOfClass:[NSString class]]) {
                w = [(NSString *)amountObj floatValue];
            }
        }
        // 也从输入框获取（双保险）
        if (w <= 0.001 && _gFields && i < _gFields.count) {
            id field = _gFields[i];
            if ([field respondsToSelector:@selector(text)]) {
                w = [[field performSelector:@selector(text)] floatValue];
            }
        }
        if (w <= 0.001) continue;

        // 获取色浆名称
        NSString *name = nil;
        if (_gNames && i < _gNames.count) {
            id nameObj = _gNames[i];
            if ([nameObj isKindOfClass:[NSString class]]) {
                name = nameObj;
            }
        }
        if (!name) name = [NSString stringWithFormat:@"色浆%lu", (unsigned long)i];

        // 从数据库查找光谱数据
        KMPigment *pigment = [KMPigmentDatabase pigmentWithName:name];
        if (pigment) {
            [pigments addObject:pigment];
            [weights addObject:@(w)];
        }
        // 如果数据库中找不到该色浆，静默跳过
        // (用户需要将色浆名称改为预设名称如"钛白""铁红"等)
    }

    if (pigments.count == 0) {
        // 没有任何已知色浆 → 返回灰色
        return [UIColor grayColor];
    }

    // KM 混合!
    KMMixResult *result = [KMEngine mixPigments:pigments weights:weights];
    return result.displayColor;
}


// ============================================================
// 新的 checkTapped: 用 KM + CIEDE2000 替代旧的 RGB 对比
// ============================================================
static void km_checkTapped(id self, SEL _cmd, id sender) {
    // --- 1. KM 混合 ---
    UIColor *mixedColor = km_mixColor(self, @selector(mixColor));

    // --- 2. 获取目标色 ---
    UIColor *targetColor = nil;
    if (_gTargetView) {
        targetColor = _gTargetView.backgroundColor;
    }
    if (!targetColor || targetColor == [UIColor clearColor]) {
        targetColor = [UIColor whiteColor];
    }

    // --- 3. 更新当前色显示 ---
    if (_gCurrentView) {
        _gCurrentView.backgroundColor = mixedColor;
    }

    // --- 4. CIEDE2000 色差 ---
    CGFloat diff = [KMEngine deltaEFromTargetColor:targetColor mixResult:nil];

    // 直接用 LAB 值计算
    CGFloat tL, ta, tb;
    [KMEngine colorToLab:targetColor L:&tL a:&ta b:&tb];

    CGFloat mL, ma, mb;
    [KMEngine colorToLab:mixedColor L:&mL a:&ma b:&mb];

    diff = [KMEngine deltaE2000_L1:tL a1:ta b1:tb L2:mL a2:ma b2:mb];

    // --- 5. 更新状态标签 ---
    if (_gStatusLabel) {
        NSString *grade;
        if (diff < 1.0)       grade = @"🏆 完美!";
        else if (diff < 3.0)  grade = @"✅ 优秀";
        else if (diff < 6.0)  grade = @"👍 良好";
        else if (diff < 12.0) grade = @"⚠️ 一般";
        else                  grade = @"❌ 再试试";

        _gStatusLabel.text = [NSString stringWithFormat:
            @"ΔE00=%.2f %@\nL*=%.0f a*=%.1f b*=%.1f",
            diff, grade, mL, ma, mb];
    }

    // --- 6. 更新最佳记录 ---
    if (diff < _gBestDifference || _gBestDifference == 0) {
        _gBestDifference = diff;
    }

    // --- 7. 如果原版有额外的 checkTapped 逻辑, 也调用一下 ---
    //      但不调用，因为它的色差计算是我们替换的目标
    //      original_checkTapped 保留但不使用

    // --- 8. 保存历史 ---
    if (_gHistory && mixedColor && targetColor) {
        NSDictionary *entry = @{
            @"target": targetColor,
            @"mixed": mixedColor,
            @"deltaE": @(diff),
            @"timestamp": [NSDate date],
        };
        [_gHistory addObject:entry];
    }
}


// ============================================================
// +load: 在 dylib 加载时执行方法交换
// ============================================================

// 前向声明，让 constructor 函数可以使用
@interface KMHooks : NSObject
+ (void)install;
@end

__attribute__((constructor))
static void KMHooksInit(void) {
    // 延迟到 UIKit 初始化之后
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 0.1 * NSEC_PER_SEC),
                   dispatch_get_main_queue(), ^{
        [KMHooks install];
    });
}

@implementation KMHooks

+ (void)install {
    Class mixVC = NSClassFromString(@"MixViewController");
    if (!mixVC) {
        NSLog(@"[KMEngine] MixViewController not found, hooks not installed");
        return;
    }

    NSLog(@"[KMEngine] Installing KM hooks on %@", mixVC);

    // --- 交换 mixColor ---
    SEL mixSel = NSSelectorFromString(@"mixColor");
    Method mixMethod = class_getInstanceMethod(mixVC, mixSel);
    if (mixMethod) {
        original_mixColor = (id(*)(id, SEL))method_getImplementation(mixMethod);
        method_setImplementation(mixMethod, (IMP)km_mixColor);
        NSLog(@"[KMEngine] ✓ mixColor → KM engine");
    } else {
        // 如果原版没有 mixColor，添加一个
        class_addMethod(mixVC, mixSel, (IMP)km_mixColor, "@@:");
        NSLog(@"[KMEngine] ✓ mixColor added (was missing)");
    }

    // --- 交换 checkTapped: ---
    SEL checkSel = NSSelectorFromString(@"checkTapped:");
    Method checkMethod = class_getInstanceMethod(mixVC, checkSel);
    if (checkMethod) {
        original_checkTapped = (void(*)(id, SEL, id))method_getImplementation(checkMethod);
        method_setImplementation(checkMethod, (IMP)km_checkTapped);
        NSLog(@"[KMEngine] ✓ checkTapped: → KM + CIEDE2000");
    }

    NSLog(@"[KMEngine] All hooks installed. 预设色浆: %@",
          [KMPigmentDatabase allPigmentNames]);
}

@end
