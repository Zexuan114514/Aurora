/* Aurora 前端 · DOM 元素表（P4.3-a，P4.3-k 加 esc）
 *
 * 视图模块都要拿界面元素，所以这张表从 app.js 里搬出来单独一份：
 *   - `$`：按 id 取元素，取不到就记进 `missingIds`（HTML 与 JS 对不上时能在
 *     `window.__auroraErrors` 里看到，而不是整页静默死掉）
 *   - `el`：启动时一次性把所有用到的元素抓成一张表（缺的元素值是 undefined，
 *     视图里 `if (!el.x)` 那种判断继续有效）
 *   - `esc`：拼 HTML 时的转义（视图模块也要拼模板，所以放这里）
 */

export const missingIds = new Set();

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const $ = (id) => {
  const node = document.getElementById(id);
  if (!node) missingIds.add(id);
  return node;
};

export const el = {
    boot: $("boot"), empty: $("empty"), view: $("view"),
    hall: $("hall"), hallRow: $("hallRow"), hallViewport: $("hallViewport"),
    hallName: $("hallName"), hallSub: $("hallSub"), hallCount: $("hallCount"),
    sortMenu: $("sortMenu"), btnBack: $("btnBack"),
    search: $("searchInput"),
    searchClear: $("searchClear"),
    title: $("gTitle"), logo: $("gLogo"), chips: $("gChips"), desc: $("gDesc"),
    play: $("btnPlay"), playLabel: $("playLabel"),
    fetching: $("fetching"), fetchTitle: $("fetchTitle"), fetchSub: $("fetchSub"),
    pillSource: $("pillSource"), pillRunning: $("pillRunning"),
    bgPanel: $("bgPanel"), bgGrid: $("bgGrid"), bgCount: $("bgCount"),
    detailPanel: $("detailPanel"), detailBody: $("detailBody"),
    dTitle: $("dTitle"), dSub: $("dSub"),
    matchPanel: $("matchPanel"), matchList: $("matchList"), matchQuery: $("matchQuery"),
    matchLinks: $("matchLinks"), matchHint: $("matchHint"), matchQuick: $("matchQuick"),
    sourcePanel: $("sourcePanel"), sourceList: $("sourceList"), sourceForm: $("sourceForm"),
    coverPanel: $("coverPanel"), coverGrid: $("coverGrid"),
    steamPanel: $("steamPanel"), steamList: $("steamList"),
    steamImport: $("steamImport"), steamSub: $("steamSub"),
    steamPickHint: $("steamPickHint"),
    getPanel: $("getPanel"), getSiteForm: $("getSiteForm"),
    getQuery: $("getQuery"), getDir: $("getDir"),
    getDirHint: $("getDirHint"), getWatch: $("getWatch"), getExtract: $("getExtract"),
    getSites: $("getSites"), addMenu: $("addMenu"),
    localePanel: $("localePanel"),
    translateHint: $("translateHint"),
    showOriginal: $("btnShowOriginal"),
    moreMenu: $("moreMenu"),
    settingsView: $("settingsView"), setNav: $("setNav"),
    categoriesView: $("categoriesView"), viewSwitch: $("viewSwitch"),
    catRoots: $("catRoots"), catShelves: $("catShelves"), catStatusList: $("catStatusList"),
    catDevs: $("catDevs"), catWall: $("catWall"), catBar: $("catBar"),
    catTitle: $("catTitle"), catSub: $("catSub"), catActions: $("catActions"),
    catCreate: $("catCreate"), catName: $("catName"), catHint: $("catHint"),
    catQuery: $("catQuery"), catSort: $("catSort"),
    scopePill: $("scopePill"), scopeLabel: $("scopeLabel"), scopeMenu: $("scopeMenu"),
    vntextPanel: $("vntextPanel"), vnThreads: $("vnThreads"), vnState: $("vnState"),
    vnHistory: $("vnHistory"), frameBox: $("frameBox"), frameImg: $("frameImg"),
    frameSel: $("frameSel"),
    netStatus: $("netStatus"), netResults: $("netResults"),
    leStatus: $("leStatus"), leProfiles: $("leProfiles"),
    toast: $("toast"),
    dropHint: $("dropHint"),
    modal: $("modal"), modalTitle: $("modalTitle"), modalBody: $("modalBody"),
    modalInput: $("modalInput"), modalOk: $("modalOk"), modalCancel: $("modalCancel"),
  };
