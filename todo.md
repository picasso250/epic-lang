## src/*.ep eat dog food
- 使用新特征  ADT
- 原则：向python对齐。（除非ep实现更优雅高效

  type Token {
      text: str # 公共字段能力
      line: i64
      Plain   # 必须要有某种 反射拿到 "Plain" 否则 dump就很丑  parser.ep 的 AstNode 更是如此
      FString {
          parts: FStringPart[]
      }
  }

  type FStringPart {
      Text {
          text: str
      }
      Expr {
          text: str
      }
  }

py 拆 codegen

python -> epic-py: 9.77s
  epic-py -> epic-epic: 10.55s
  epic-epic -> epic-epic-epic: 11.31s
  epic-epic-epic -> epic-epic-epic-epic: 11.18s
  bootstrap fixed point reached



  我们开发遇到了障碍。我们正在开发这条线  parser->mir->lowIR(asm)->obj->link->exe
    显然 mir->asm->obj 这条线还有bug
    可以通过

我们看看py实现（只要python test_examples_py.py --backend machine即可），之前存在这些问题
 - MirLower.lower() 现在无条件塞入所有 runtime helper。这个会让测试、输出、后续按需链接都变重，是最明显的“喉返神经”。
  - X64Program 没有 validator，错误拖到 encoder 才暴露。更糟的是已有隐患：test a, b 当前会忽略第二个 operand；add r64, imm 的 imm8 路径有截断风险。
  - MachineObjectBuilder 缺少公开的 build-result API，测试只能碰 private 方法。应该拆出 build_machine_object() 返回 bytes/data/labels/relocs。
  - MIR validator 落后于实际 MIR。实际已经有 struct.new、field.load、array.push、adt.payload 等 op，但 unknown op 基本没被验证。
  - program.structs 是动态挂到 MirProgram 上的隐藏合约，后续 Epic 移植会难受。
  - 文档里 module symbol 用 @main，实现里用 raw main。要在自举 backend 前定死内部符号拼写和打印拼写。
  - src/epic.ep 仍是旧 NASM 工具链，这没问题，但要明确它是下一阶段迁移对象，不能把 Python machine examples 通过误认为 self-hosted backend 已支持。
  这些问题现在还存在吗？如果存在，哪个问题的优先级最高？

i32 u32 
cstr(str) (检查cstr合法性，否则 die)
os.user32.MessageBoxA(0, cstr("hi"), cstr("Epic"), u32(0))
  os.kernel32.Sleep(u32(1000))

清理过时 buildin 

grill-me 兄弟技能 user know nothing about code （认知空间 高层A决策如何影响你所知的BCD


os.user32.MessageBoxA(0, cstr("hi"), cstr("Epic"), u32(0))
  os.kernel32.Sleep(u32(1000))