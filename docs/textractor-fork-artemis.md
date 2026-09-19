# 参考：Textractor 分支（Chenx221）的 Artemis x64 实现

来源：	exthook/engine/match64.cc @ b1ee9d4（Textractor 的 64 位引擎匹配移植版）。
**只看思路，不抄它的特征码数据**（GPL，且逐游戏维护成本高）。

## 它是怎么做的

1. **给 x64 造了一个「合成 pushad 帧」**：pusha_off 枚举把 rax/rbx/…/r15 各自排成
   8 字节一格（pusha_rax_off=-0xC 一路到 pusha_r15_off=-0x84），再用

   `c
   #define regof(name, rsp_base)  (*(uintptr_t*)((rsp_base) + pusha_##name##_off - 4))
   `

   去读寄存器。那个 -4 就是 ITH 兼容偏移 —— 于是**上游那套按「寄存器偏移」写的 x86
   钩子定义几乎不用改就能在 x64 上跑**。

2. **Artemis64 钩子**（InsertArtemis64Hook）：在可执行内存里搜函数序言

   `
   48 89 5C 24 20 55 56 57 41 54 41 55 41 56 41 57 48 83 EC 60
   `

   命中就 hp.address = addr、hp.type = USING_STRING | USING_UTF8、
   hp.offset = -0x24 - 4（= **RDX**，x64 第 2 个参数）→ 文本是 **UTF-8 指针**。

3. **另一条 InsertArtemisHook**（Chenx221 补的）：按不同版本攒特征码，例如
   CC 40 57 48 83 EC 40 48 C7 44 24 30 … → 在 ddr+1 挂钩、读 **RDI**、
   USING_STRING | USING_UTF8 | NO_CONTEXT；下面还跟着 ytes2 处理更新的变体。
   每个变体都附了 VNDB 样例游戏，属于「遇到一款补一条」的维护方式。

4. **代码区上限放宽**：MAX_REL_ADDR = 0x00300000（3 MB），注释直说
   「Certain game engine like Artemis has larger code region」。

## 对 Aurora 的新思路（可落地）

1. **x64 的文本指针经常在寄存器里，不在栈上。** 他们的 Artemis64 读的是 RDX、另一条读 RDI；
   我们的采样式查找器目前只扫**栈槽**，所以这类码抓不到（我们在 アマカノ３ 上找到的
   HS65001#20@38A78:emotedriver.dll 恰好是个栈参数版）。改进：采样时把
   GetThreadContext 的寄存器值也当候选来源（按 Textractor 的合成 pushad 布局换算成
   它的偏移写法），就能自动产出 HS…@addr 这种寄存器码 —— 这是下一步最值得做的事。
2. **签名播种**：他们靠「每个变体一条特征码」；我们可以自建（**自己**从游戏二进制里取字节、
   自己实测验证）同族签名库，命中即得候选地址，省掉十几秒采样。
3. **UTF-8 得到独立印证**：USING_STRING | USING_UTF8 与我们实测 S + 65001# 一致。
4. **代码区别按老引擎的 2 MB 设上限**：Artemis 这类引擎代码段更大，做近调用/相对地址
   扫描时要放宽（他们用 3 MB）。
