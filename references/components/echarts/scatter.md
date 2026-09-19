# ECharts 散点图

散点图用于观察两个数值变量的关系、聚类和异常点。每个点至少包含 `[x, y]`。

````md
```echarts size=760x460
{
  "title": { "text": "延迟与负载关系", "left": "center" },
  "xAxis": { "type": "value", "name": "负载 (%)" },
  "yAxis": { "type": "value", "name": "P95 延迟 (ms)" },
  "series": [
    {
      "name": "采样",
      "type": "scatter",
      "symbolSize": 10,
      "data": [[25, 82], [40, 95], [55, 121], [70, 190], [85, 340]]
    }
  ]
}
```
````

不要仅凭视觉相关宣称因果关系。需要标记特殊点时，可增加单独系列并在图后解释筛选条件。
