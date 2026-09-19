# Mermaid Gantt

用于有明确日期或相对依赖的项目计划。没有可信日期时不要编造工期，可改成流程或阶段表。

## 模板

````md
```mermaid
gantt
  title 发布计划
  dateFormat YYYY-MM-DD
  section 准备
  需求确认 :done, req, 2026-08-01, 5d
  方案设计 :active, design, after req, 7d
  section 实施
  开发 :dev, after design, 14d
  验证 :test, after dev, 5d
```
````

## 编写方法

- `dateFormat` 与实际日期格式保持一致。
- 使用稳定的任务 ID，依赖写 `after <id>`。
- `done`、`active` 只反映已有状态。
- 阶段超过 4-6 个或任务过细时，拆成总览和详细计划。

甘特图用于沟通计划，不替代项目管理系统中的责任人、工时和变更历史。
