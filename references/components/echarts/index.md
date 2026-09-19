# ECharts

ECharts 用 JSON option 描述定量数据图。AI Docs 在构建期通过 SSR 生成亮色和暗色静态 SVG，不保留 tooltip、hover、点击筛选或 dataZoom 交互。

## 选型

| 需求 | 文档 |
| --- | --- |
| 类别比较、时间趋势、多系列 | `bar-line.md` |
| 少量类别占比或构成 | `pie.md` |
| 二维关系、分布、异常值 | `scatter.md` |
| 多维指标画像 | `radar.md` |

## JSON 约束

- fence 内容必须能被 `JSON.parse` 解析。
- 键和字符串使用双引号。
- 不允许注释、尾逗号、函数、变量、模板字符串或 `undefined`。
- formatter 只能使用 ECharts 支持的字符串模板；不能写 JavaScript 函数。

## 数据原则

- 标题、轴名、单位、图例和时间范围要完整。
- 多系列颜色和顺序保持稳定。
- 类别过多时使用水平条形图或拆图。
- 静态图中不要依赖 tooltip 才能看到关键数值。
