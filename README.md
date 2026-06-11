# Kubelka-Munk 色浆混合引擎 — 集成指南

## 📁 文件清单

```
Tiaose-KM/
├── km_engine.py           # Python 验证版 (已通过测试, 可直接运行)
├── KMPigment.h/.m         # 色浆数据模型 → 拖入 Xcode
├── KMEngine.h/.m          # KM 混合引擎核心 → 拖入 Xcode
├── KMPigmentDatabase.h/.m # 预设 8 种色浆库 → 拖入 Xcode
└── README.md              # 你正在看的这个文件
```

## 🔧 集成到你的 App (Xcode)

### 第 1 步: 添加文件
将 6 个 `.h/.m` 文件拖入 Xcode 项目，勾选 "Copy items if needed"。

### 第 2 步: 替换旧代码

**删除/注释掉旧方法:**
- `mixColor`      → 替换为 `[KMEngine mixPigments:weights:]`
- `toLab`        → 替换为 `[KMEngine colorToLab:...]`
- `colorDifference` → 替换为 `[KMEngine deltaE2000_L1:a1:b1:L2:a2:b2:]`

### 第 3 步: 修改 `checkTapped:` (核心改动)

```objc
// ===== 旧代码 (RGB 加权混合) =====
// UIColor *mixedColor = [self mixColor];  // 旧的加法混合
// CGFloat diff = [self colorDifference:mixedColor target:targetColor];

// ===== 新代码 (KM 光谱混合) =====
#import "KMEngine.h"
#import "KMPigmentDatabase.h"

- (void)checkTapped:(id)sender {
    // 1. 收集色浆和重量
    NSMutableArray<KMPigment *> *pigments = [NSMutableArray array];
    NSMutableArray<NSNumber *> *weights = [NSMutableArray array];

    for (int i = 0; i < self.pigmentCount; i++) {
        NSString *name = self.pigmentNames[i];
        CGFloat amount = [self.amountFields[i].text floatValue];

        if (amount > 0.01) { // 忽略 0 用量
            KMPigment *p = [KMPigmentDatabase pigmentWithName:name];
            if (p) {
                [pigments addObject:p];
                [weights addObject:@(amount)];
            }
        }
    }

    if (pigments.count == 0) return;

    // 2. KM 混合
    KMMixResult *result = [KMEngine mixPigments:pigments weights:weights];

    // 3. 显示结果
    self.currentColorView.backgroundColor = result.displayColor;
    self.statusLabel.text = [NSString stringWithFormat:
        @"L*=%.0f a*=%.1f b*=%.1f", result.L, result.a, result.b];

    // 4. 计算色差
    CGFloat deltaE = [KMEngine deltaEFromTargetColor:self.targetColor
                                           mixResult:result];
    self.deltaELabel.text = [NSString stringWithFormat:@"ΔE00 = %.2f", deltaE];

    // 5. 更新最佳记录
    if (deltaE < self.bestDeltaE) {
        self.bestDeltaE = deltaE;
    }
}
```

### 第 4 步: 修改色浆添加逻辑

```objc
- (void)addPigmentTapped:(id)sender {
    // 使用预设色浆库
    NSArray<NSString *> *available = [KMPigmentDatabase allPigmentNames];
    // available = @[@"钛白", @"炭黑", @"铁红", @"酞青蓝",
    //               @"铬黄", @"酞青绿", @"永固红", @"群青"]

    // 弹出选择器让用户选色浆...
}
```

## 🎨 添加自定义色浆

你的用户可能有特定品牌的色浆，可以用反射率关键点定义:

```objc
KMPigment *myPigment = [KMPigmentDatabase
    pigmentWithName:@"自配铁红"
    keyWavelengths:@[@380, @430, @500, @550, @580, @620, @730]
    keyReflectances:@[@0.03, @0.025, @0.018, @0.02, @0.15, @0.48, @0.74]];
```

关键波长代表该色浆的反射率在不同波长上的特征点。反射率数据可以:
1. 从颜料厂商获取（如 Golden, Winsor & Newton 提供光谱数据）
2. 用分光光度计测量
3. 从已知配方反推

## 🧪 测试 (Python)

```bash
# 运行测试验证引擎
python3 km_engine.py
```

## 📐 公式速查

| 步骤 | 公式 |
|------|------|
| 混合 K/S | (K/S)_mix,λ = Σ(c_i × (K/S)_i,λ) |
| K/S → 反射率 | R = 1 + K/S - √((1+K/S)² - 1) |
| 反射谱 → XYZ | X = k·Σ(R·D65·x̄) |
| XYZ → LAB | L* = 116·f(Y/Yn) - 16 |
| 色差 | CIEDE2000 (ISO 11664-6) |

## ⚠️ 注意事项

1. **必须加钛白**: 不加钛白的话混合结果会非常暗，因为是减法混色。
   建议默认配方里始终包含 100-500g 钛白作为基料。

2. **光谱数据精度**: 当前使用通用颜料光谱数据，与市售具体品牌的色浆
   可能有偏差。v3.1 计划加入标定功能。

3. **浓度线性假设**: 单常数 KM 模型假设 (K/S) 与浓度线性相关，
   在颜料浓度 < 20% 时精度很高，浓度过高时可能有偏差。
