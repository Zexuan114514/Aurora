/* Aurora 前端 · 推送事件分发（P4.3-r）
 *
 * 后端（14 个事件主题）通过 `window.__aurora.emit(topic, payload)` 推过来，
 * 这里把每个主题的处理收成一张表：主模块只留 `emit` 入口，具体动作由 ctx 注入
 * （渲染、焦点、批量刷新、各视图的更新口子…）。
 *
 * 约定：未知主题直接忽略；单个主题抛错只记 console，不影响其它事件。
 */
import { $, el } from "./dom.js";
import { state } from "./store.js";

export function createEventRouter(ctx) {
  /* 搜索结束却没有封面：说明图片是界面侧加载（走系统代理），同一个游戏只提醒一次 */
  const coverHinted = new Set();

  function hintCoverOnce(game) {
    if (!game || !game.id || coverHinted.has(game.id)) return;
    if (game.cover || game.custom_cover || (game.cover_sources || []).length) return;
    coverHinted.add(game.id);
    ctx.toast("没抓到封面：图片由界面直接加载（走系统代理），可在「设置 → 网络」测试连通性", 5400);
  }

  /* 转区启动的落点提示：LE 没装或带不动时照样启动，只说明一句 */
  function notifyLocaleStart(mode) {
    if (mode === "no-le") {
      ctx.toast("没检测到 Locale Emulator，已按普通方式启动", 4600);
    } else if (mode === "unsupported-target") {
      ctx.toast("目标不是 32 位 exe，Locale Emulator 带不动，已按普通方式启动", 4600);
    } else if (mode === "locale") {
      ctx.toast("已用指定的 LE 配置转区启动");
    } else if (mode === "locale-default") {
      ctx.toast("已用 LE 默认配置转区启动");
    }
  }

  /* 一个游戏实体的运行状态变化（启动 / 结束 / 元数据回填） */
  function onGameState(event, payload) {
    const running = event === "game:running" ? true
      : event === "game:stopped" ? false : payload.running;
    const isNew = ctx.upsertGame(payload, { running });
    ctx.setBusy(payload.id, false);
    ctx.render();
    if (event === "game:running") notifyLocaleStart(payload.locale);
    if (event === "game:updated" && payload.metadata_state === "ok") hintCoverOnce(payload);
    // 库里原本没有这个游戏（导入/拖放）时，把焦点挪过去并换上它的壁纸
    if (isNew && !ctx.currentGame()) ctx.setFocus(payload.id);
    // 当前游戏换了壁纸（背景面板 / 其它来源）时跟着换
    else if (payload.id === state.focus) ctx.scheduleBackground();
  }

  const handlers = {
    "game:updated": (payload) => onGameState("game:updated", payload),
    "game:stopped": (payload) => onGameState("game:stopped", payload),
    "game:running": (payload) => onGameState("game:running", payload),

    "metadata:searching": (payload) => {
      ctx.setBusy(payload.id, true);
      ctx.renderHall();
    },

    "games:imported": (payload) => {
      // 拖放/导入进来的游戏：并进大厅并聚焦最后一个
      (payload.games || []).forEach((g) => ctx.upsertGame(g));
      const ids = payload.ids || [];
      ctx.render();
      if (ids.length) ctx.setFocus(ids[ids.length - 1]);
      const ignored = payload.ignored || 0;
      ctx.toast(ids.length ? `已导入 ${ids.length} 个游戏` : "没有可导入的 exe"
                + (ignored ? "（已忽略非 exe 文件）" : ""), ids.length ? 2600 : 4000);
    },

    "metadata:notfound": (payload) => {
      ctx.setBusy(payload.id, false);
      let g = ctx.findGame(payload.id);
      if (!g && payload.game) {
        ctx.pushGame(payload.game);
        if (!ctx.currentGame()) state.focus = payload.id;
        g = payload.game;
      }
      if (g) {
        ctx.patchGame(payload.id, { metadata_state: "notfound",
                                    metadata_note: payload.note });
      }
      ctx.render();
      // 只有正看着这个游戏时才弹候选面板；
      // 大厅里、以及设置页里都只提示一句，别把面板盖到别的界面上
      if (state.focus === payload.id && state.page === "game" && !payload.quiet
          && !state.settingsOpen) {
        ctx.openCandidates(payload.candidates, "",
                           payload.note || "没有找到匹配结果");
        ctx.toast(payload.note || "没有找到匹配结果");
      } else if (g && !payload.quiet) {
        ctx.toast(`${g.name}：${payload.note || "没有找到匹配结果"}`, 3600);
      }
    },

    "batch:progress": (payload) => {
      const batch = state.batch;
      if (!batch) return;
      batch.done = payload.done;
      batch.total = payload.total;
      if (batch.kind === "steam") {
        el.steamImport.textContent = `导入中 ${payload.done}/${payload.total}`;
      } else if (batch.kind === "translate") {
        $("translateHint").textContent = `${payload.done}/${payload.total}`;
      } else {
        $("refreshHint").textContent = `${payload.done}/${payload.total}`;
      }
    },

    "batch:done": (payload) => {
      const batch = state.batch;
      state.batch = null;
      $("refreshHint").textContent = "";
      $("translateHint").textContent = "";
      if (batch && batch.kind === "steam") {
        ctx.updateSteamHint();
        ctx.toast(`Steam 导入完成：${payload.imported || 0} 个游戏`);
        ctx.refreshLibrary().catch(() => {});
      } else if (batch && batch.kind === "translate") {
        ctx.toast(`简介翻译完成：翻译 ${payload.translated || 0} 个，跳过 ${payload.skipped || 0} 个`
          + (payload.failed ? `，失败 ${payload.failed} 个` : ""), 4200);
        ctx.refreshLibrary().catch(() => {});
      } else {
        ctx.toast(`已重新抓取 ${payload.total} 个游戏的信息`);
      }
    },

    "metadata:error": (payload) => {
      ctx.setBusy(payload.id, false);
      ctx.render();
      ctx.toast("搜索出错：" + payload.note);
    },

    "translate:done": (payload) => {
      // 只有手动点「翻译简介」才回执，自动翻译安静进行
      if (!payload.manual) return;
      const provider = String(payload.provider || "");
      if (payload.changed) {
        // P6.4：插件引擎也要如实回执（provider = plugin:<id>）
        if (provider.startsWith("plugin:")) ctx.toast(`已用插件 ${provider.slice(7)} 翻译简介`);
        else ctx.toast(provider === "llm" ? "已用 LLM 翻译简介" : "已用免费接口翻译简介");
      } else if (payload.error === "empty") {
        ctx.toast("这款游戏还没有简介可翻译");
      } else if (payload.error === "stale") {
        ctx.toast("简介刚被更新，请再翻译一次");
      } else if (payload.error === "busy") {
        ctx.toast("正在翻译中…");
      } else if (payload.error === "plugin-unavailable") {
        ctx.toast("翻译插件不可用（没加载或已被禁用），详情见「设置 → 插件」");
      } else if (payload.error === "plugin-failed") {
        ctx.toast("翻译插件调用失败，简介保持原文；详情见「设置 → 插件」");
      } else if (payload.error) {
        ctx.toast("翻译失败：" + payload.error);
      } else {
        ctx.toast("简介已经是中文，无需翻译");
      }
    },

    "vntext:status": (payload) => {
      if (el.vntextPanel.classList.contains("open")) ctx.vntext.renderPanel(payload);
    },

    // 查找器的每一步都从总线推过来，面板即时更新（不再只靠 1.5s 轮询兜底）
    "hooksearch:status": (payload) => ctx.vntext.onHookSearch(payload),

    "vntext:line": () => {
      if (state.settingsOpen && state.settingsTab === "vntext") ctx.vntext.renderGlossary();
      if (el.vntextPanel.classList.contains("open")) ctx.vntext.refreshSoon();
    },

    "downloads:status": (payload) => {
      if (payload.kind === "warn") {
        ctx.toast(payload.text || "下载目录里有个文件处理不了", 5200);
      } else if (payload.kind === "extracted") {
        ctx.toast(`已自动解压 ${payload.name}`, 2600);
      } else if (payload.kind === "imported") {
        const n = payload.count || 0;
        ctx.toast(n ? `下载目录里发现 ${n} 个游戏，已自动导入` : "下载目录有更新", 3800);
        ctx.refreshLibrary().then(() => ctx.render()).catch(() => {});
      }
    },
  };

  /** 后端推来的事件入口：未知主题忽略，单个主题出错不影响别的。 */
  function emit(event, payload) {
    const handler = handlers[event];
    if (!handler) return;
    try {
      handler(payload || {});
    } catch (err) {
      console.error(err);
    }
  }

  return { emit };
}
