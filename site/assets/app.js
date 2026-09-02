(function () {
  "use strict";

  const header = document.querySelector("[data-header]");
  const nav = document.querySelector("[data-nav]");
  const menuButton = document.querySelector("[data-menu-toggle]");

  function updateHeader() {
    header?.classList.toggle("is-solid", window.scrollY > 18);
  }

  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  menuButton?.addEventListener("click", function () {
    const open = nav?.classList.toggle("open") ?? false;
    document.body.classList.toggle("menu-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.textContent = open ? "Close" : "Menu";
  });

  nav?.addEventListener("click", function (event) {
    if (!event.target.closest("a")) return;
    nav.classList.remove("open");
    document.body.classList.remove("menu-open");
    menuButton?.setAttribute("aria-expanded", "false");
    if (menuButton) menuButton.textContent = "Menu";
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !nav?.classList.contains("open")) return;
    nav.classList.remove("open");
    document.body.classList.remove("menu-open");
    menuButton?.setAttribute("aria-expanded", "false");
    if (menuButton) menuButton.textContent = "Menu";
    menuButton?.focus();
  });

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", async function () {
      const source = button.getAttribute("data-copy") || "";
      const target = source.startsWith("#") ? document.querySelector(source) : null;
      const value = target?.textContent?.trim() || source;
      const original = button.textContent;
      try {
        await navigator.clipboard.writeText(value.replace(/^\$\s*/, ""));
        button.textContent = "Copied";
      } catch {
        const temporary = document.createElement("textarea");
        temporary.value = value.replace(/^\$\s*/, "");
        temporary.setAttribute("readonly", "");
        temporary.style.position = "fixed";
        temporary.style.opacity = "0";
        document.body.appendChild(temporary);
        temporary.select();
        const copied = document.execCommand("copy");
        temporary.remove();
        button.textContent = copied ? "Copied" : "Copy failed";
      }
      window.setTimeout(function () { button.textContent = original; }, 1400);
    });
  });

  const replay = document.querySelector("[data-replay]");
  if (replay) {
    const runButton = replay.querySelector("[data-replay-run]");
    const resetButton = replay.querySelector("[data-replay-reset]");
    const hunks = Array.from(replay.querySelectorAll("[data-hunk]"));
    const tests = Array.from(replay.querySelectorAll("[data-test]"));
    const log = replay.querySelector("[data-run-log]");
    const record = replay.querySelector("[data-record]");
    let removed = new Set();
    let busy = false;

    const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
    const evaluate = () => [!removed.has(1) && !removed.has(2), !(removed.has(2) && !removed.has(1)), true];

    async function runTests() {
      tests.forEach((test) => { test.dataset.result = "run"; });
      await wait(360);
      const results = evaluate();
      results.forEach((passes, index) => { tests[index].dataset.result = passes ? "pass" : "fail"; });
      return results.every(Boolean);
    }

    function writeLog(line, append) {
      if (!log) return;
      log.textContent = append ? `${log.textContent}\n${line}` : line;
    }

    function resetState() {
      removed = new Set();
      hunks.forEach((hunk) => {
        hunk.dataset.state = "";
        hunk.dataset.verdict = "";
      });
      record?.classList.remove("show");
    }

    runButton?.addEventListener("click", async function () {
      if (busy) return;
      busy = true;
      runButton.disabled = true;
      resetState();
      writeLog("Replaying six bounded counterfactual runs.");
      for (let id = 1; id <= hunks.length; id += 1) {
        const hunk = hunks.find((item) => Number(item.dataset.hunk) === id);
        if (!hunk) continue;
        removed = new Set([id]);
        hunk.dataset.state = "removed";
        hunk.dataset.verdict = "testing";
        const passes = await runTests();
        hunk.dataset.verdict = passes ? "noise" : "core";
        hunk.dataset.state = "";
        writeLog(`Hunk ${id} removed: ${passes ? "evidence still holds" : "evidence fails"}.`, true);
        await wait(180);
      }
      removed = new Set();
      await runTests();
      record?.classList.add("show");
      writeLog("Causal core isolated: hunks 1 and 2.", true);
      busy = false;
    });

    resetButton?.addEventListener("click", async function () {
      if (busy) return;
      resetState();
      if (runButton) runButton.disabled = false;
      await runTests();
      writeLog("Full change applied. 3/3 pass.\nThis is where most review stops.");
    });
  }

  const filterButtons = Array.from(document.querySelectorAll("[data-guide-filter]"));
  const guideCards = Array.from(document.querySelectorAll("[data-guide-category]"));
  filterButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      const filter = button.dataset.guideFilter;
      filterButtons.forEach((item) => item.classList.toggle("active", item === button));
      guideCards.forEach((card) => {
        card.hidden = filter !== "all" && card.dataset.guideCategory !== filter;
      });
    });
  });

  const billingButtons = Array.from(document.querySelectorAll("[data-billing]"));
  const prices = Array.from(document.querySelectorAll("[data-monthly][data-annual]"));
  billingButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      const mode = button.dataset.billing;
      billingButtons.forEach((item) => item.classList.toggle("active", item === button));
      prices.forEach((price) => {
        price.textContent = price.dataset[mode] || price.textContent;
      });
      document.querySelectorAll("[data-billing-note]").forEach((note) => {
        note.textContent = mode === "annual" ? "per month, billed annually" : "per month";
      });
    });
  });

  document.querySelectorAll("[data-faq-question]").forEach(function (button) {
    button.addEventListener("click", function () {
      const item = button.closest(".faq-item");
      const open = item?.classList.toggle("open") ?? false;
      button.setAttribute("aria-expanded", String(open));
      const icon = button.querySelector("[data-faq-icon]");
      if (icon) icon.textContent = open ? "−" : "+";
    });
  });
})();
