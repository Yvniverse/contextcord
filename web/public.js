(function () {
  "use strict";
  const copy = window.CONTEXTCORD_I18N || {};
  const localeKey = "contextcord-locale";
  const themeKey = "contextcord-theme";
  const get = (value, path) => path.split(".").reduce((current, part) => current && current[part], value);
  let locale = localStorage.getItem(localeKey) || (navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");

  function applyLocale() {
    if (!copy[locale]) locale = "en";
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const value = get(copy[locale], node.dataset.i18n);
      if (value !== undefined) node.innerHTML = value;
    });
    document.querySelectorAll("[data-i18n-attr]").forEach((node) => {
      node.dataset.i18nAttr.split(",").forEach((attr) => {
        const value = get(copy[locale], node.dataset["i18n" + attr.charAt(0).toUpperCase() + attr.slice(1)]);
        if (value !== undefined) node.setAttribute(attr, value);
      });
    });
    document.querySelectorAll("[data-locale-button]").forEach((node) => {
      node.textContent = get(copy[locale], "common.language") || (locale === "zh" ? "EN" : "中文");
    });
  }

  function applyTheme() {
    const saved = localStorage.getItem(themeKey);
    if (saved === "dark" || saved === "light") document.documentElement.dataset.theme = saved;
    const button = document.querySelector("[data-theme-button]");
    if (button) button.textContent = document.documentElement.dataset.theme === "dark" ? "☀" : "☾";
  }

  document.querySelectorAll("[data-locale-button]").forEach((node) => node.addEventListener("click", () => {
    locale = locale === "zh" ? "en" : "zh";
    localStorage.setItem(localeKey, locale);
    applyLocale();
  }));
  const themeButton = document.querySelector("[data-theme-button]");
  if (themeButton) themeButton.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem(themeKey, next);
    applyTheme();
  });
  applyTheme();
  applyLocale();

}());
