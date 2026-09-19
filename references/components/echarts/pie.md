# ECharts 饼图

ECharts 饼图适合少量类别构成，比 Mermaid 饼图提供更完整的 legend 和 label 配置。

````md
```echarts size=680x420
{
  "title": { "text": "成本构成", "left": "center" },
  "legend": { "orient": "vertical", "left": "left" },
  "series": [
    {
      "name": "成本",
      "type": "pie",
      "radius": "55%",
      "label": { "formatter": "{b}: {d}%" },
      "data": [
        { "name": "计算", "value": 48 },
        { "name": "存储", "value": 27 },
        { "name": "网络", "value": 15 },
        { "name": "其他", "value": 10 }
      ]
    }
  ]
}
```
````

`"{b}: {d}%"` 是字符串模板，不是 JavaScript 函数，符合 JSON 限制。

类别超过 7 个、扇区大小接近或需要精确排序时，改用水平条形图。
