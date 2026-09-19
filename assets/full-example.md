# AI Docs Viewer 全功能测试

> 本文档测试所有图表类型和功能。

---

## 1. Mermaid 流程图

```mermaid size=760x420
flowchart TD
    A[用户输入] --> B{解析类型}
    B -->|Markdown| C[渲染正文]
    B -->|Mermaid| D[渲染图表]
    B -->|Markmap| F[渲染思维导图]
    C --> G[展示页面]
    D --> G
    F --> G
    G --> H{用户操作}
    H -->|打印| I[系统打印]
    H -->|返回| A
```

## 2. Mermaid 时序图

```mermaid
sequenceDiagram
    participant U as 用户
    participant B as Build脚本
    participant H as HTML页面
    participant M as Mermaid

    U->>B: node build.js input.md
    B->>B: 读取依赖 & Markdown
    B->>H: 生成自包含HTML
    U->>H: 浏览器打开
    H->>M: 渲染图表
    M-->>H: 返回SVG
    H->>U: 展示完整文档
```

## 3. Mermaid 甘特图

```mermaid
gantt
    title 项目开发计划
    dateFormat  YYYY-MM-DD
    section 需求分析
    用户调研       :done,    des1, 2024-01-01, 7d
    需求文档       :done,    des2, after des1, 5d
    section 设计
    UI设计         :active,  des3, after des2, 10d
    架构设计       :         des4, after des2, 8d
    section 开发
    前端开发       :         dev1, after des3, 20d
    后端开发       :         dev2, after des4, 20d
```

## 4. Mermaid ER 图

```mermaid
erDiagram
    USER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
    USER {
        int id PK
        string name
        string email
    }
    ORDER {
        int id PK
        date created_at
        string status
    }
```

## 5. Mermaid 饼图

```mermaid
pie title 技术栈分布
    "TypeScript" : 35
    "Python" : 25
    "Go" : 15
    "Rust" : 10
    "其他" : 15
```

## 6. Mermaid 状态图

```mermaid
stateDiagram-v2
    [*] --> 待处理
    待处理 --> 进行中 : 开始处理
    进行中 --> 已完成 : 处理完成
    进行中 --> 已取消 : 取消
    已完成 --> [*]
    已取消 --> [*]
    已完成 --> 待处理 : 重新打开
```

## 7. Mermaid 依赖图

```mermaid
flowchart TB
    Browser[浏览器] -->|HTTPS| NextJS[Next.js App]
    NextJS -->|读写| SQLite[(SQLite)]
    NextJS -->|缓存| Redis[(Redis)]
```

## 8. ECharts 图表

```echarts
{
  "title": { "text": "技术栈分布", "left": "center" },
  "tooltip": { "trigger": "item" },
  "legend": { "orient": "vertical", "left": "left" },
  "series": [
    {
      "name": "语言",
      "type": "pie",
      "radius": "50%",
      "data": [
        { "value": 35, "name": "TypeScript" },
        { "value": 25, "name": "Python" },
        { "value": 15, "name": "Go" },
        { "value": 10, "name": "Rust" },
        { "value": 15, "name": "其他" }
      ],
      "emphasis": {
        "itemStyle": { "shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.5)" }
      }
    }
  ]
}
```

## 9. 横向布局

::: columns
::: column
### 左侧摘要

- 正文宽度可配置为 50%–100%
- 适合并列展示说明与实现

:::
::: column
### 右侧代码

```javascript
const contentWidth = 80;
console.log(`${contentWidth}%`);
```
:::
:::

## 10. 分栏内图表

::: columns
::: column
### 左列流程

```mermaid size=640x360
flowchart TB
    A[输入] --> B[解析]
    B --> C[渲染]
```

```mermaid size=640x360
flowchart LR
    Input[输入] --> Output[输出]
```
:::
::: column
### 右列数据

```echarts size=640x360
{
  "title": { "text": "列内趋势", "left": "center" },
  "xAxis": { "type": "category", "data": ["一", "二", "三"] },
  "yAxis": { "type": "value" },
  "series": [{ "type": "line", "data": [12, 19, 16] }]
}
```

```markmap size=640x360
# 列内导图
## 预览
## 导出
```
:::
:::

## 11. 交互式思维导图

```markmap
# AI Docs Viewer
## 核心功能
### Markdown 渲染
### Mermaid 图表
- 流程图 / 时序图 / 甘特图
- ER图 / 饼图 / 状态图
### Mermaid 关系图
- 依赖图 / 网络拓扑
### ECharts
- 数据可视化
### 交互思维导图
### 数学公式
### 代码高亮
## 特性
### 完全离线
### 暗色主题
### 响应式布局
### 打印导出
```

## 12. 数学公式

行内公式：质能方程 $E = mc^2$，欧拉公式 $e^{i\pi} + 1 = 0$。

二次方程求根公式：

$$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$

矩阵：

$$\begin{pmatrix} a & b \\ c & d \end{pmatrix} \begin{pmatrix} x \\ y \end{pmatrix} = \begin{pmatrix} ax + by \\ cx + dy \end{pmatrix}$$

积分：

$$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$

求和：

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

## 13. 代码高亮

### TypeScript

```typescript
interface Config {
  theme: 'light' | 'dark';
}

function init(config: Config): void {
  console.log(`Theme: ${config.theme}`);
}
```

### Python

```python
from dataclasses import dataclass

@dataclass
class Document:
    title: str
    content: str

    def render(self) -> str:
        return f"<h1>{self.title}</h1>"
```

### SQL

```sql
SELECT u.name, COUNT(o.id) AS order_count
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
GROUP BY u.id
ORDER BY order_count DESC;
```

## 14. 表格

| 图表类型 | 引擎 | 代码块 | 离线 |
|---------|------|--------|------|
| 流程图/时序图/甘特图/ER图/饼图/状态图 | Mermaid | `mermaid` | ✅ |
| 依赖图/网络拓扑 | Mermaid | `mermaid` | ✅ |
| 数据图表 | ECharts | `echarts` | ✅ |
| 交互思维导图 | Markmap | `markmap` | ✅ |
| 数学公式 | KaTeX | `$...$` / `$$...$$` | ✅ |
| 代码高亮 | highlight.js | 语言名 | ✅ |

---

> 所有功能完全离线可用，无外部依赖。
