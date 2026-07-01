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

现有 parser 限制：Python 版 unary - 没有进 parse_unary