# Mermaid Sequence Diagram

用于接口调用、认证握手、同步/异步消息和失败重试。横轴是参与者，纵轴是时间顺序。

## 模板

````md
```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Web
  participant A as API
  participant D as 数据库

  U->>W: 提交请求
  W->>A: POST /items
  A->>D: 写入记录
  D-->>A: 返回 ID
  A-->>W: 201 Created
  W-->>U: 显示结果
```
````

## 箭头语义

- `->>`：调用或消息。
- `-->>`：返回或响应。
- `-)`：异步消息，可在确认 Mermaid 版本支持后使用。

## 可选结构

````md
```mermaid
sequenceDiagram
  participant C as Client
  participant S as Service
  C->>S: 请求
  alt 校验成功
    S-->>C: 200
  else 校验失败
    S-->>C: 400
  end
```
````

只保留理解交互必需的消息。内部函数调用过多时，合并成一个有业务意义的步骤。
