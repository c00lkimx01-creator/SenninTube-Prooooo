/* Sennin Tube Pro v1.2 - Global Shell JS
   v1.3.5
   - Themes (light/dark/glass) with persistence
   - Corner actions (menu+settings) on non-home pages
*/
(function () {
    "use strict";

    var THEME_KEY = "st-theme";

    function getTheme() {
        var t = localStorage.getItem(THEME_KEY);
        if (t === "light" || t === "dark" || t === "glass") return t;
        return (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
            ? "dark" : "light";
    }
    function applyTheme(t) {
        document.documentElement.setAttribute("data-theme", t);
        localStorage.setItem(THEME_KEY, t);
        document.querySelectorAll(".st-theme-switch button").forEach(function (b) {
            b.classList.toggle("active", b.dataset.theme === t);
        });
    }
    applyTheme(getTheme());

    // Remove any legacy sidebar elements that earlier versions injected/cached
    function removeLegacySidebar() {
        ["st-sidebar", "st-sidebar-toggle", "st-sidebar-backdrop"].forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.parentNode) el.parentNode.removeChild(el);
        });
        document.body.classList.remove(
            "st-has-sidebar",
            "st-sidebar-collapsed",
            "st-mobile-sidebar-open",
            "st-is-home"
        );
    }

    function ready(fn) {
        if (document.readyState !== "loading") fn();
        else document.addEventListener("DOMContentLoaded", fn);
    }

    ready(function () {
        removeLegacySidebar();
        markHomePage();
        injectThemeSwitcher();
        injectCornerActions();
        // Remove any legacy top-bar hide button & state from earlier versions
        var legacyBtn = document.getElementById("st-topbar-toggle");
        if (legacyBtn && legacyBtn.parentNode) legacyBtn.parentNode.removeChild(legacyBtn);
        document.body.classList.remove("st-topbar-hidden");
        try { localStorage.removeItem("st-topbar-hidden"); } catch (e) {}
    });

    function isHome() {
        var p = location.pathname.replace(/\/+$/, "");
        return p === "" || p === "/";
    }
    function markHomePage() {
        if (isHome()) document.body.classList.add("st-page-home");
    }

    function injectThemeSwitcher() {
        var panel = document.querySelector("#settings-panel .settings-content");
        if (!panel || panel.querySelector(".st-theme-switch")) return;

        var wrap = document.createElement("div");
        wrap.className = "settings-option";
        wrap.style.marginBottom = "25px";
        wrap.innerHTML =
            '<p style="font-size:14px; margin-bottom:6px; font-weight:600;">テーマ</p>'
          + '<small style="display:block; margin-bottom:10px;">外観モードを選んでください</small>'
          + '<div class="st-theme-switch">'
          +   '<button type="button" data-theme="light"><i class="fas fa-sun"></i>ライト</button>'
          +   '<button type="button" data-theme="dark"><i class="fas fa-moon"></i>ダーク</button>'
          +   '<button type="button" data-theme="glass"><i class="fas fa-snowflake"></i>グラス</button>'
          + '</div>';
        panel.insertBefore(wrap, panel.firstChild);

        wrap.querySelectorAll("button").forEach(function (b) {
            b.addEventListener("click", function () {
                applyTheme(b.dataset.theme);
            });
        });
        applyTheme(getTheme());
    }

    /* On non-home pages that don't already have menu/settings nav,
       inject floating corner buttons that open the existing panels. */
    function injectCornerActions() {
        if (isHome()) return;
        if (document.getElementById("st-corner-actions")) return;

        var wrap = document.createElement("div");
        wrap.id = "st-corner-actions";

        var hasSettings = document.getElementById("settings-panel");
        var hasMenu = document.getElementById("menu-panel");

        if (hasMenu) {
            var mBtn = document.createElement("button");
            mBtn.type = "button";
            mBtn.title = "メニュー";
            mBtn.innerHTML = '<i class="fas fa-th-large"></i>';
            mBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                document.getElementById("settings-panel") &&
                    document.getElementById("settings-panel").classList.remove("open");
                document.getElementById("menu-panel").classList.add("open");
            });
            wrap.appendChild(mBtn);
        } else {
            // No menu panel on this page → link to home menu actions via direct nav
            var mBtn2 = document.createElement("button");
            mBtn2.type = "button";
            mBtn2.title = "ホーム";
            mBtn2.innerHTML = '<i class="fas fa-th-large"></i>';
            mBtn2.addEventListener("click", function () { location.href = "/"; });
            wrap.appendChild(mBtn2);
        }

        if (hasSettings) {
            var sBtn = document.createElement("button");
            sBtn.type = "button";
            sBtn.title = "設定";
            sBtn.innerHTML = '<i class="fas fa-cog"></i>';
            sBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                hasMenu && hasMenu.classList.remove("open");
                document.getElementById("settings-panel").classList.add("open");
            });
            wrap.appendChild(sBtn);
        } else {
            // Inject a minimal settings panel for theme switching
            var panel = document.createElement("div");
            panel.id = "settings-panel";
            panel.style.cssText =
                "position:fixed;top:0;right:-320px;width:320px;height:100%;" +
                "background:var(--st-surface);color:var(--st-text);z-index:2001;" +
                "box-shadow:-10px 0 40px rgba(0,0,0,0.15);" +
                "transition:right 0.35s cubic-bezier(0.165,0.84,0.44,1);" +
                "padding:40px 26px;box-sizing:border-box;border-left:1px solid var(--st-border);";
            panel.innerHTML =
                '<style>#settings-panel.open{right:0 !important;}</style>' +
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;border-bottom:1px solid var(--st-border);padding-bottom:14px;">' +
                '  <h2 style="margin:0;font-size:18px;"><i class="fas fa-cog"></i> 設定</h2>' +
                '  <button id="st-close-mini-settings" style="background:none;border:none;color:var(--st-text);font-size:16px;cursor:pointer;"><i class="fas fa-times"></i></button>' +
                '</div>' +
                '<div class="settings-content"></div>' +
                '<div style="margin-top:30px;font-size:12px;opacity:.6;">Ver 1.3.5</div>';
            document.body.appendChild(panel);

            var sBtn3 = document.createElement("button");
            sBtn3.type = "button";
            sBtn3.title = "設定";
            sBtn3.innerHTML = '<i class="fas fa-cog"></i>';
            sBtn3.addEventListener("click", function (e) {
                e.stopPropagation();
                panel.classList.add("open");
            });
            wrap.appendChild(sBtn3);

            document.body.addEventListener("click", function () {
                panel.classList.remove("open");
            });
            panel.addEventListener("click", function (e) { e.stopPropagation(); });
            panel.querySelector("#st-close-mini-settings")
                .addEventListener("click", function () { panel.classList.remove("open"); });

            // Re-run theme switcher injection now that the panel exists
            injectThemeSwitcher();
        }

        document.body.appendChild(wrap);
    }
})();
