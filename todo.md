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