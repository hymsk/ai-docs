# ECharts 柱状图与折线图

柱状图适合类别之间比较，折线图适合有顺序的时间趋势。两者可组合，但轴和单位必须明确。

## 折线图

````md
```echarts size=760x420
{
  "title": { "text": "最近四周请求量", "left": "center" },
  "legend": { "top": 30, "data": ["请求量"] },
  "xAxis": { "type": "category", "name": "周", "data": ["W1", "W2", "W3", "W4"] },
  "yAxis": { "type": "value", "name": "次" },
  "series": [
    { "name": "请求量", "type": "line", "data": [1200, 1480, 1390, 1710] }
  ]
}
```
````

## 柱状图

````md
```echarts
{
  "title": { "text": "各环境失败数", "left": "center" },
  "xAxis": { "type": "category", "data": ["开发", "测试", "生产"] },
  "yAxis": { "type": "value", "name": "次" },
  "series": [
    { "name": "失败", "type": "bar", "data": [42, 17, 3] }
  ]
}
```
````

## 柱线组合

若两个系列单位不同，使用两个 yAxis 并给出 `yAxisIndex`。单位相同则不要引入双轴。

静态 SVG 不显示 tooltip，关键数值需要通过轴、标签或图后表格表达。类别名很长时使用水平条形图：`xAxis` 为 value，`yAxis` 为 category。
