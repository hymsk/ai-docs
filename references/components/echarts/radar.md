# ECharts 雷达图

雷达图适合比较少量对象在多个同量纲或已归一化指标上的画像。不同单位的原始指标不能直接放在同一雷达图中。

````md
```echarts size=700x500
{
  "title": { "text": "方案能力对比", "left": "center" },
  "legend": { "top": 30, "data": ["方案 A", "方案 B"] },
  "radar": {
    "indicator": [
      { "name": "性能", "max": 100 },
      { "name": "可靠性", "max": 100 },
      { "name": "易维护", "max": 100 },
      { "name": "成本优势", "max": 100 }
    ]
  },
  "series": [
    {
      "type": "radar",
      "data": [
        { "name": "方案 A", "value": [85, 78, 66, 72] },
        { "name": "方案 B", "value": [70, 88, 82, 60] }
      ]
    }
  ]
}
```
````

必须说明评分方法。若没有一致量表，改用表格列出原始指标和单位。
