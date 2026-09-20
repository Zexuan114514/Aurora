"""JS 桥接 mixins：每个模块按域聚合一组方法，最终由 gl/api.py 的 Api 类继承。

约定：mixin 只做参数整形、校验与调用编排，业务规则在 app/services（P3.2 起逐步下沉）。
pywebview 只暴露 js_api 对象的顶层方法，所以方法名必须保持在同一个 Api 实例上 —— 这是用
mixin 而不是组合对象的原因（见 docs/adr/ADR-0006）。
"""
