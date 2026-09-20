"""文本规则（纯函数）：折叠重复书写、去重、折行拼接、说话人合并、杂讯判定。

P1 分层时从 `gl/vntext.py` 原样搬出；行为由 `tests/fixtures/golden/text_rules.golden.json` 卡住。
"""
from __future__ import annotations

import difflib
import re



#: 钩子文本里常见的菜单/系统提示，翻译它们只会干扰阅读
NOISE_WORDS = ("无法注入", "Usage:", "Textractor:", "请以管理员", "注入失败","設定", "セーブ", "ロード", "タイトル", "終了", "バックログ", "スキップ",
               "オプション", "コンフィグ", "ウィンドウ", "フルスクリーン", "音量", "戻る",
               "はじめから", "つづきから", "終わります", "よろしいですか",
               # Textractor 自己的状态行（实测会被当台词送去翻译）
               "vnreng", "hijacking", "注入钩子", "管道已连接", "INSERT ", "disable GDI hooks",
               "已连接", "successfully attached")



#: 折叠「连续重复字符」时要放过的字符：这些连写本身有意义（「！！」「……」），
#: 折掉会改坏原文。注意「「「」这种引号连写一定是写缓冲痕迹，不能放过。
KEEP_RUN_CHARS = set("。、，．,.！？!?…‥ー〜～゛゜")


NAME_PREFIX_RE = re.compile(r"^(?:\u3010[^\u3011]{1,12}\u3011|\[[^\]]{1,12}\]|\uff3b[^\uff3d]{1,12}\uff3d)+")


def _kana_fold(ch: str) -> str:
    """片假名折成平假名：引擎逐字双写时常出现「ぺペ」这种混写配对。"""
    code = ord(ch)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return ch


def collapse_doubling(body: str) -> str:
    """每个字符恰好重复 2 次 → 压成 1 个。只用于「判断是不是同一句」，不动展示文本。"""
    out: list[str] = []
    i = 0
    while i < len(body):
        if i + 1 < len(body) and _kana_fold(body[i]) == _kana_fold(body[i + 1]):
            out.append(body[i])
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def normalize_for_dedupe(text: str) -> str:
    """去重用的归一化：折叠重复（含逐字双写）+ 去掉开头的【名字】+ 去掉标点空白。

    同一句台词常以三种形态先后到达：带名字前缀版、逐字重复版、干净版。
    归一化后它们是同一个串，只翻一次就够。
    """
    body = clean_hook_text(text)
    body = NAME_PREFIX_RE.sub("", body).strip()
    body = collapse_doubling(body)
    # 注意：长音符 `ー` 不算标点，"あー" 折成 "あ" 会让短句去重失效（实测 Siglus）
    return re.sub(r"[\s\u300c\u300d\u300e\u300f\u3010\u3011\[\]\uff08\uff09()、。，,.!\uff01?\uff1f"
                  r"\u2026\u301c~\u30fb:\uff1a;\uff1b-]", "", body)


RUN_RE = re.compile(r"(.)\1{2,}", re.DOTALL)


def collapse_runs(body: str) -> str:
    """把「同一个字连续重复 ≥3 次」压成 1 个（引擎逐字写缓冲时会这样）。

    只压 3 次以上：日文里的「！！」「……」这类两连是有意义的，不能动。
    """
    out = RUN_RE.sub(r"\1", body)
    tokens = out.split()
    if len(tokens) >= 2 and len(set(tokens)) == 1:
        out = tokens[0]                       # 「ABC ABC」这种整串重复
    return out


def collapse_repeats(text: str) -> str:
    """把「整行是同一段重复」还原成一段（Textractor 常见的重复句问题）。

    例：AAABBBCCC → ABC；【佑斗】【佑斗】【佑斗】 → 【佑斗】；
        おおおいいいいーー → おいー
    """
    body = (text or "").strip()
    n = len(body)
    if n >= 4:
        for period in range(1, n // 2 + 1):
            if n % period:
                continue
            block = body[:period]
            if block and block * (n // period) == body:
                return collapse_runs(block)
    return collapse_runs(body)


# --------------------------------------------------------------------------- #
# 写缓冲痕迹的还原
#
# 实测（DRACU RIOT / TVP-KIRIKIRI）：钩子拿到的是游戏「往同一个对话框缓冲区
# 反复写、每次重画都重写一遍」的过程，于是一行里会出现同一句台词的多个形态：
#     【佑斗】【佑斗】【佑斗】ABC AABBCC ABC
#     なななかかか…（逐字×3）  ・  …だだだ。。。今今にに至至るる…（×3 + ×2）
# 直接送去翻译就会把三段都翻一遍、或者翻出带重复的怪句子（用户反馈的
# 「三形态文本」）。下面这几个函数负责把「能证明是写缓冲痕迹」的部分还原成一句。
# --------------------------------------------------------------------------- #
def fold_char_runs(body: str, min_run: int = 3) -> str:
    """同一个字连续 ≥min_run 次 → 折成 1 个；标点/长音符等天然连写的字符不动。

    「なななかかか」→「なかなか」；「。。。」「！！」原样保留。
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        j = i + 1
        while j < n and body[j] == ch:
            j += 1
        run = j - i
        if run >= min_run and ch not in KEEP_RUN_CHARS:
            out.append(ch)
        else:
            out.append(ch * run)
        i = j
    return "".join(out)


def _pair_run(body: str, start: int) -> int:
    """从 start 开始「成对相同」的对数（ぺペ 这种平/片假名混写也算一对）。"""
    pairs = 0
    i = start
    while i + 1 < len(body) and _kana_fold(body[i]) == _kana_fold(body[i + 1]):
        pairs += 1
        i += 2
    return pairs


def fold_doubling_spans(body: str, min_pairs: int = 3) -> str:
    """折叠「整段逐字双写」的片段，只折能证明的：连续 ≥min_pairs 对全部成对相同。

    「ここ」这类正常的叠字只有 1 对，永远不会被折；实测的引擎双写形态
    （「今今にに至至るる」「おははよようう」）动辄十几对，一定能被抓到。
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        pairs = _pair_run(body, i)
        if pairs >= min_pairs:
            out.append("".join(body[i + 2 * k] for k in range(pairs)))
            i += 2 * pairs
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


_PUNCT_EDGE = "。、，．,.！？!?…‥・「」『』（）()[]【】 \t\u3000"


def _skeleton(body: str) -> tuple[str, list[int], list[int]]:
    """骨架：去掉标点/引号/空白、连续相同字符合一，并记下每个骨架字符在原文里
    的起止位置（还原时把标点补回来）。"""
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, ch in enumerate(body):
        if ch in _PUNCT_EDGE or ch in "「」『』【】":
            continue
        if chars and chars[-1] == ch:
            ends[-1] = index
            continue
        chars.append(ch)
        starts.append(index)
        ends.append(index)
    return "".join(chars), starts, ends


def longest_repeat(body: str) -> str:
    """最长「至少出现两次」的子串（朴素后缀排序；台词行都很短，够用）。"""
    n = len(body)
    if n < 2:
        return ""
    order = sorted(range(n), key=lambda index: body[index:])
    best = ""
    for left, right in zip(order, order[1:]):
        if left > right:
            left, right = right, left
        size = 0
        while right + size < n and body[left + size] == body[right + size]:
            size += 1
        if size > len(best):
            best = body[left:left + size]
    return best


def _repeat_coverage(body: str, core: str) -> int:
    """整行里有多少字符属于「core 或它被截断的副本」。"""
    variants = [core]
    for cut in range(1, max(1, len(core) // 4) + 1):
        variants.append(core[:-cut])
    variants = [row for row in variants if len(row) >= 4]
    covered = 0
    index = 0
    n = len(body)
    while index < n:
        hit = 0
        for variant in variants:
            if body.startswith(variant, index):
                hit = len(variant)
                break
        if hit:
            covered += hit
        index += hit or 1
    return covered


def compare_key(text: str) -> str:
    """比较用骨架：去掉标点引号空白，并把连续相同字符压成一个。"""
    chars: list[str] = []
    for ch in text:
        if ch in _PUNCT_EDGE or ch in "「」『』【】":
            continue
        if chars and chars[-1] == ch:
            continue
        chars.append(ch)
    return "".join(chars)


def _similar(left: str, right: str, threshold: float = 0.6) -> bool:
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= threshold


def _collapse_quote_forms(body: str) -> str:
    """「形态1」「形态2」「形态3」——同一句被写多遍，各份之间是 」「。

    实测（DRACU RIOT）每一行都是这个结构：逐字×3 形态、×2 形态、干净形态，
    每份都被引号包住。只要判定这些份是同一句（骨架相似），就留最后一份
    ——写缓冲越写越准，最后一份就是干净的那句。
    """
    if "」「" not in body:
        return body
    parts = [part for part in body.split("」「") if part.strip()]
    if len(parts) < 2:
        return body
    folded = [collapse_repeats(fold_doubling_spans(fold_char_runs(part))) for part in parts]
    keys = [compare_key(part) for part in folded]
    last = keys[-1]
    if len(last) < 6:
        return body
    if not any(_similar(last, key) for key in keys[:-1]):
        return body
    out = folded[-1].strip()
    # 分隔符「」「」把最后一份的左引号留在了上一份的结尾，这里补/去多余括号，
    # 免得译文里带一个孤零零的 」
    while out and out[-1] in "」』" and out.count("「") < out.count("」"):
        out = out[:-1].rstrip()
    return out or body


def _collapse_by_coverage(body: str) -> str:
    """没有引号分隔时（例如「X。。X。X」「ABC AABBCC ABC」）按骨架重复判定。"""
    n = len(body)
    if n < 8 or n > 400:
        return body
    skeleton, starts, ends = _skeleton(body)
    total = len(skeleton)
    if total < 8:
        return body
    unit = longest_repeat(skeleton)
    if len(unit) < 4:
        return body
    chosen = ""
    best = (0, 0, 0)
    for size in range(4, len(unit) + 1):
        for candidate in (unit[:size], unit[-size:]):
            if len(candidate) < 4 or skeleton.count(candidate) < 2:
                continue
            covered = _repeat_coverage(skeleton, candidate)
            if covered < 0.85 * total:
                continue
            # 又长又铺得满的优先；打平时优先「落在行尾」的那份 —— 写缓冲最后写的
            # 才是当前这一句（跨份错位选出来的候选不会落在行尾）
            score = (covered * len(candidate), int(skeleton.endswith(candidate)),
                     len(candidate))
            if score > best:
                best, chosen = score, candidate
    if not chosen:
        return body
    last = skeleton.rfind(chosen)
    if last < 0:
        return body
    begin = starts[last]
    end = ends[last + len(chosen) - 1]
    # 只把左引号/左括号补回来；句号、逗号属于上一句，不能吞
    while begin > 0 and body[begin - 1] in "「『（([【":
        begin -= 1
    while end + 1 < n and body[end + 1] in _PUNCT_EDGE:      # 右引号/句读补回来
        end += 1
    return body[begin:end + 1].strip() or body


def collapse_duplicated_sentence(body: str) -> str:
    """同一句被写进同一行多遍（写缓冲的历史）时只留一份。

    实测原文（DRACU RIOT，一行三个形态）：
        【佑斗】×3「「「でででももも…？？？」」」「「ででもも…？？」」「でも…？」
    先按「」「」拆形态（最常见），拆不出来再按骨架重复覆盖率兜底。
    """
    collapsed = _collapse_quote_forms(body)
    if collapsed != body:
        return collapsed
    return _collapse_by_coverage(body)


def fold_written_repeats(text: str) -> str:
    """折叠全部写缓冲痕迹：逐字×N、成对双写、同句多份、整串重复。"""
    return collapse_repeats(collapse_duplicated_sentence(
        fold_doubling_spans(fold_char_runs(text))))


_CJK = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f"


_CJK_GAP_RE = re.compile(rf"(?<=[{_CJK}])[ \t\u3000]+(?=[{_CJK}])")


def tidy_ocr_text(text: str) -> str:
    """整理 OCR 结果：Windows OCR 会把日文按字切开（「出 会 っ て」），
    汉字/假名之间的空格要去掉，否则译文会被当成一堆孤立字。

    实测 アマカノ３（引擎自绘文字、只能走 OCR）：文本框的边框会被读成孤立的
    `-`/`ー`/`|`，还会在词中间插一个 `-`（`こ - んなの`）；标点两侧也会多出空格。
    这些都清掉，交给翻译的才是干净的台词。
    """
    body = " ".join(str(text or "").split())
    body = _CJK_GAP_RE.sub("", body)
    body = _OCR_DASH_RE.sub(" ", body)                     # 边框/连字符噪声
    body = _OCR_LONE_DASH_RE.sub(" ", body)                # 孤立的 `ー`（长音符在词里才有意义）
    body = re.sub(r"\s+([、。，．！？!?…‥」』）〕】])", r"\1", body)
    body = re.sub(r"([（〔【「『])\s+", r"\1", body)
    body = re.sub(rf"([、。，．！？!?…‥」』）〕】])\s+(?=[{_CJK}])", r"\1", body)
    body = _CJK_GAP_RE.sub("", body)
    return " ".join(body.split())


#: OCR 会把文本框边框/分隔线读成这些东西（日文里的破折号是 ―/—，不在这里）
_OCR_DASH_RE = re.compile(r"\s*[-‐‑|｜]+\s*")


#: 孤立的 `ー`（前后都是空白/边界）也是边框噪声；词里的长音符不受影响（コーヒー）
_OCR_LONE_DASH_RE = re.compile(r"(?<!\S)[ー\u2015]+(?!\S)")


_WRAP_CJK_RE = re.compile(rf"[{_CJK}\u3000-\u303f\uff01-\uff60]")


def join_wrapped(left: str, right: str) -> str:
    """把引擎折行后的续行接回一句：日文直接相连，西文之间补空格。"""
    if not left:
        return right
    if not right:
        return left
    if _WRAP_CJK_RE.match(left[-1]) or _WRAP_CJK_RE.match(right[0]):
        return left + right
    return f"{left} {right}"


def looks_like_speaker_name(text: str) -> bool:
    """像不像「说话人名字」那一行。

    不少引擎把名字单独发一条（实测悠刻のファムファタル 的 `アマリリス`）：很短、
    没有标点、也不是完整句子。这种行不该单独翻一句，应该并到下一句当【名字】。
    """
    body = (text or "").strip()
    if not body or len(body) > 12 or "\n" in body:
        return False
    if re.search(r"[。、，．！？!?…「」『』（）()\[\]]", body):
        return False
    return bool(re.search(rf"[{_CJK}]", body))


def split_name_prefix(body: str) -> tuple[str, str]:
    """拆开开头的【名字】前缀（可能重复写了多遍），返回 (名字, 正文)。"""
    match = NAME_PREFIX_RE.match(body)
    if not match:
        return "", body
    parts = re.findall(r"【[^】]{1,12}】|\[[^\]]{1,12}\]|［[^］]{1,12}］", match.group(0))
    names: list[str] = []
    for part in parts:
        # 引擎重画名字时会插空格（实测「【 佑斗 】」），统一压掉，译文才会干净
        clean = re.sub(r"\s+", "", part)
        if clean not in names:
            names.append(clean)
    return "".join(names), body[match.end():].lstrip()


def norm_name(text: str) -> str:
    """名字比较用：小写 + 去掉空白/下划线/点（「RIDDLE JOKER」==「RiddleJoker」）。"""
    return re.sub(r"[\s\-_.·]+", "", str(text or "").lower())


_SENTENCE_END_RE = re.compile(r"[。．！？!?…」』]")


def fold_full_doubling(text: str) -> str:
    """整串都成对时才折一半（`女女子子`→`女子`）；`アマリリス` 这种正常叠音不动。"""
    body = str(text or "")
    if len(body) < 2 or len(body) % 2:
        return body
    if all(_kana_fold(body[i]) == _kana_fold(body[i + 1])
           for i in range(0, len(body), 2)):
        return body[::2]
    return body


def is_subsequence(short: str, long: str) -> bool:
    """short 的字符是否按顺序出现在 long 里（用来认「缺字变体」）。

    实测 Siglus 的 GDI 钩子会把同一句吐成只剩汉字的版本：`空雲落み` 之于
    `まるで、空から白い雲のかたまりが落ちてきたみたいに。`，正好是子序列。
    """
    if not short or not long or len(short) > len(long):
        return False
    it = iter(long)
    return all(ch in it for ch in short)


_CJK_ANY_RE = re.compile(rf"[{_CJK}]")



#: 按字形抓的 GDI 钩子（会漏字的那一类）
_GLYPH_HOOK_RE = re.compile(r"GetGlyphOutline|GetGlyphIndices|TextOut|ExtTextOut", re.I)


def _strip_ws(text: str) -> str:
    """判「缺字版」时把空白压掉：GDI 钩子吐出来的残片里常夹着空格
    （实测 WillPlus：真句 `姉さんは真面目を絵に…`，残片 `真面絵描 約束違真似`），
    带着空格去做子序列判断会直接失败、把残片当成新台词。"""
    return re.sub(r"\s+", "", str(text or ""))


def missing_chars_variant(short: str, long: str) -> bool:
    """`short` 是不是 `long` 的「缺字版」（同一句只画出来一部分）。

    实测 秽翼のユースティア（BGI/Ethornell）：同一个进程里 `TextOutA` 钩子按字形
    抓文本，字体里查不到的字就丢，吐出来的是 `視界黒塞`；引擎自带钩子随后吐出
    完整句 `視界を黒い何かが塞いだ。`。缺字版正好是完整版的**子序列**。
    """
    short = _strip_ws(short)
    long = _strip_ws(long)
    if len(short) < 3 or len(long) < 6:
        return False
    if len(short) > 0.8 * len(long):
        return False           # 只差一两个字：交给原来的相似度去重，别在这里动
    if not is_subsequence(short, long):
        return False
    # 整句正好是长句的开头（标点不算）→ 更像「短句被续写成下一句」
    # （`誰か。` → `誰か説明してほしい`），不是缺字版：缺字的版本是**中间**丢字，
    # 不会只剩开头那么多
    if normalize_for_dedupe(long).startswith(normalize_for_dedupe(short)):
        return False
    kept = len(_CJK_ANY_RE.findall(short))
    return kept >= max(3, int(0.6 * len(short)))


def looks_like_short_fragment(probe: str, pool) -> bool:
    """`probe` 是不是 pool 里某一句的残片（缺字/漏字的同一句）。

    两条历史规则（Siglus 实测）：
    ① 短、有汉字、没有句读，且是 pool 里某句的子序列（`群群飛飛`→`群飛`）；
    ② 比 pool 里最长的短 30% 以上，且每个字都能在 pool 里找到（变体有时是
       相邻两句拼起来的，例如 `遅２羽励寄添`）。
    """
    probe = _strip_ws(probe)
    texts = [_strip_ws(text) for text in (pool or [])]
    texts = [text for text in texts if text]
    if not texts or not (2 <= len(probe) <= 12) or _SENTENCE_END_RE.search(probe):
        return False
    if len(CJK_RE.findall(probe)) < max(2, len(probe) // 2):
        return False           # 只对「汉字为主」的残片动手，别误伤说话人名字
    if any(len(old) >= 4 and is_subsequence(probe, old) for old in texts):
        return True
    recent = texts[-4:]
    joined = "".join(recent)
    return len(probe) <= 0.7 * max(len(text) for text in recent) \
        and all(ch in joined for ch in probe)


#: 同一个进程里常常有两条钩子线程吐同一句台词的两份（完整版 + 缺字版）。
#: 先把候选行压住一小会，等这一批的两个版本都到齐再决定翻哪一份 —— 不这样做
#: 就会出现「同一句翻两遍、先翻缺字的再翻完整的」（实测 秽翼のユースティア）。
VARIANT_SETTLE = 0.55


#: 判「这两条是同一句的两个版本」时允许的最大时间差（秒）
VARIANT_WINDOW = 1.5


def _variant_pair(left: dict, right: dict) -> bool:
    """两条候选行是不是「同一句的两个版本」。

    要求：来自**不同线程**、时间挨着，且短的那条是长的那条的缺字版/残片。
    同一个线程的前后两句台词永远不算（由分片缓冲去处理）。
    """
    if not left or not right or left.get("key") == right.get("key"):
        return False
    try:
        gap = abs(float(left.get("at") or 0) - float(right.get("at") or 0))
    except Exception:
        return False
    if gap > VARIANT_WINDOW:
        return False
    short, long = (left, right) if len(left.get("probe") or "") <= len(right.get("probe") or "") \
        else (right, left)
    short_probe = str(short.get("probe") or "")
    long_probe = str(long.get("probe") or "")
    if not short_probe or not long_probe or len(short_probe) >= len(long_probe):
        return False
    if missing_chars_variant(short_probe, long_probe):
        return True
    return looks_like_short_fragment(short_probe, [long_probe])


def looks_like_system_spam(text: str, min_repeat: int = 4) -> bool:
    """系统字符串特征：同一个片段被下划线/空白重复很多遍。

    实测 SiglusEngine（SUMMER POCKETS REFLECTION BLUE）会疯狂重发场景名与资源表：
        `10_プロローグ072510_プロローグ072510_プロローグ0725…`（同一段重复 257 次）
    这类行没有句读、同一片段反复出现。必须拿**原始文本**判：清洗会把重复折掉，
    折完只剩 `10_プロローグ0725`，反而更像一句台词了。
    """
    body = str(text or "")
    if not body or _SENTENCE_END_RE.search(body):
        return False                     # 有句读 → 更像台词，放行
    if "__sys_" in body:
        return True
    tokens = [token for token in re.split(r"[_\s]+", body) if token]
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    if tokens and max(counts.values()) >= min_repeat:
        return True
    # 超长又没有句读 → 资源表；再退一步：某个片段在行里反复出现（`nonenonenone…`）
    if len(body) > 300:
        return True
    head = body[:800]
    repeat = longest_repeat(head)
    if len(repeat) >= 3 and len(repeat) * head.count(repeat) >= 0.5 * len(head):
        return True
    return False


def clean_hook_text(text: str) -> str:
    """把写缓冲痕迹还原成一句台词；还原本就是重复噪声时返回空串。"""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    name, rest = split_name_prefix(body)
    if not rest:
        return ""                     # 只有名字（引擎单独重画了一次名字）→ 不是台词
    rest = fold_written_repeats(rest).strip()
    if not rest:
        return ""
    return f"{name}{rest}" if name else rest


def residual_artifacts(text: str) -> list[str]:
    """仍然存在的重复痕迹（自检用：干净的台词应当返回空表）。"""
    body = str(text or "")
    found: list[str] = []
    for index in range(len(body) - 2):
        if body[index] == body[index + 1] == body[index + 2] \
                and body[index] not in KEEP_RUN_CHARS:
            found.append("run3")
            break
    index = 0
    while index < len(body) - 5:
        if _pair_run(body, index) >= 3:
            found.append("doubling")
            break
        index += 1
    if _collapse_by_coverage(body) != body:
        found.append("repeat")
    return found


GARBAGE_RE = re.compile(r"[\ue000-\uf8ff\ufffd\ufff0-\uffff\x00-\x08\x0b\x0c\x0e-\x1f]")


GOOD_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff01-\uff60a-zA-Z0-9\s，。、！？…—「」『』（）()：:；;・～~ー]")



#: 台词里可能出现的字符（日文/中文/拉丁/常见标点与全角符号）。除此之外的字符
#: （天城文、希伯来文、西里尔文…）基本都是「没转区/读错编码」的乱码。
EXPECTED_RE = re.compile(
    r"[\u0020-\u007e\u00a0-\u00ff\u2010-\u203b\u203c-\u206f\u2190-\u21ff"
    r"\u2460-\u24ff\u2500-\u257f\u25a0-\u25ff\u2600-\u27bf\u3000-\u303f"
    r"\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\ufe30-\ufe4f\uff01-\uff60\uff61-\uff9f\uffe0-\uffee]")



def looks_like_garbage(text: str) -> bool:
    """乱码判定：未转区（非日语代码页）时游戏会吐出假名+私用区/控制符混杂的串。"""
    body = (text or "").strip()
    if not body:
        return True
    if GARBAGE_RE.search(body):
        return True
    # 混进了意料之外的文字系统（实测白色相簿2 的乱码线程：
    # `इव孙ؔ䝬׋孙ؔ灐灒灟灹灱炄灰` —— 天城文/希伯来文混着汉字）
    others = sum(1 for ch in body if not EXPECTED_RE.match(ch))
    if others >= 2 and others / len(body) > 0.15:
        return True
    # 注意：这一条不能太激进。钩子是分片吐文本的，被截断的短句很容易凑不够
    # 有效字符比例，如果因此判成乱码，真文本所在线程会连着被误杀（反馈里的
    # 「真文本线程被丢弃，之后再也不翻译」就是这么来的）。
    if len(body) >= 6:
        good = len(GOOD_RE.findall(body))
        if good / len(body) < 0.5:
            return True
        if len(set(body)) <= 3:
            return True
    return False



KANA_RE = re.compile(r"[\u3040-\u30ff]")


CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def looks_like_dialogue(text: str) -> bool:
    """像不像游戏里的台词：有假名、有一定长度、不是纯符号/菜单。"""
    body = (text or "").strip()
    if len(body) < 4 or len(body) > 400:
        return False
    if looks_like_noise(body):
        return False
    kana = len(KANA_RE.findall(body))
    if kana >= 2 or (kana >= 1 and len(CJK_RE.findall(body)) >= 2):
        return True
    # 短台词（「あ…」「はい」这种只有一两个假名的）也算 —— 白色相簿2 里
    # 这类句子很多，不认的话真文本线程永远当不上领跑线程
    return kana >= 1 and bool(re.match(r"^[「『（(【]", body))


def looks_like_noise(text: str, max_chars: int = 1200) -> bool:
    """过滤纯数字/符号、过短、系统菜单这类不该翻的行。"""
    body = text.strip()
    if len(body) < 2 or len(body) > max_chars:
        return True
    if not re.search(r"[^\W\d_]", body, re.UNICODE):        # 全是数字/符号
        return True
    if any(word in body for word in NOISE_WORDS):
        return True
    if "__sys_" in body:
        return True        # 引擎内部标记（实测 Siglus：__sys_scdata_init__ / __sys_bk_selline…）
    if re.match(r"^\d{1,3}_", body) and not _SENTENCE_END_RE.search(body):
        return True        # Siglus 场景名（10_プロローグ0725…），正常台词不会这么开头
    if len(re.findall(r"\(&\w\)", body)) >= 2:
        return True                    # 「ファイル(&F)画面(&S)…」菜单栏
    # 视频/窗口/文件名之类（实测白色相簿2 的 `mv01`、`ActiveMovie Window`）：
    # 纯拉丁字母数字、没标点、又很短，不可能是日文台词
    if len(body) <= 24 and re.fullmatch(r"[A-Za-z0-9_.\- ]+", body):
        return True
    if looks_like_garbage(body):
        return True
    if len(set(body)) <= 2 and len(body) >= 6:              # 分割线之类
        return True
    return False

def hook_candidate_score(text: str, *, ocr_target: str = "", count: int = 0) -> float:
    """候选钩子文本的可信度（0~1）：先看「像不像台词」，再参考与当前台词的相似度。

    为什么需要它：旧实现只按 `difflib.ratio(OCR 台词, 候选文本)` 排序，而 OCR 本身就不准，
    于是采样到的乱码（资源表、坐标串、重复名）常常排在真台词前面 —— 实测 アマカノ３
    两个候选全判失败就是这个原因。这里把「文本自身像不像人话」放在第一位：

    * 一票否决：空串 / 乱码 / 系统刷屏 / 噪声行 → 0 分
    * 加分：命中台词形态、长度合适、含假名、带句读或引号
    * 减分：长重复片段（资源表/刷屏特征）
    * OCR 相似度只占 0.25 权重，且 OCR 缺失时不影响排序
    * `count`（采样命中次数）给一点点权重，作为同分时的破局项
    """
    body = clean_hook_text(str(text or ""))
    if not body or len(body) < 2:
        return 0.0
    if looks_like_garbage(body) or looks_like_system_spam(body) or looks_like_noise(body):
        return 0.0
    score = 0.0
    if looks_like_dialogue(body):
        score += 0.55
    if 4 <= len(body) <= 120:
        score += 0.15
    if KANA_RE.search(body):
        score += 0.15
    if _SENTENCE_END_RE.search(body) or "「" in body:
        score += 0.10
    repeat = longest_repeat(body)
    if repeat and len(repeat) >= 6:
        score -= 0.20
    if ocr_target:
        score += 0.25 * difflib.SequenceMatcher(None, str(ocr_target), body).ratio()
    if count:
        score += min(0.05, 0.01 * (int(count) ** 0.5))
    return round(max(0.0, min(1.0, score)), 4)
