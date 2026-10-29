/* 小鲸鱼桌面控制台（Electron 壳）
 *
 * 行为约定：
 *  - 启动软件：自动确保「控制台后端 8787」和「小鲸鱼（AstrBot + NapCat）」都在跑
 *  - 关闭窗口：只退出这个外壳，小鲸鱼继续在后台运行
 *  - 托盘 →「退出」：停服务并退出软件进程（无确认弹窗，唯一退出入口）
 */

const { app, BrowserWindow, Tray, Menu, shell, nativeImage, dialog } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const CONSOLE_URL = "http://127.0.0.1:8787";
const HEALTH_URL = CONSOLE_URL + "/api/health";
const PYTHONW = path.join(ROOT, "tools", "astrbot", "Scripts", "pythonw.exe");
const SERVER = path.join(ROOT, "console", "server.py");
const SCRIPTS = path.join(ROOT, "scripts");
const fs = require("fs");
const LOG = path.join(ROOT, "desktop", "shell.log");
function shellLog(msg) {
  try {
    fs.appendFileSync(LOG, `[${new Date().toISOString()}] ${msg}\n`);
  } catch (e) {}
}

let mainWindow = null;
let tray = null;
let servicesState = "unknown"; // running | starting | stopped | unknown
let isQuitting = false;

/* ---------------- 工具 ---------------- */
function portOpen(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ port, host: "127.0.0.1" });
    sock.setTimeout(600);
    sock.on("connect", () => {
      sock.destroy();
      resolve(true);
    });
    sock.on("error", () => resolve(false));
    sock.on("timeout", () => {
      sock.destroy();
      resolve(false);
    });
  });
}

function pingConsole(cb) {
  const req = http.get(CONSOLE_URL + "/api/status", { timeout: 900 }, (res) => {
    res.resume();
    cb(true);
  });
  req.on("error", () => cb(false));
  req.on("timeout", () => {
    req.destroy();
    cb(false);
  });
}

/* ---------------- 健康状态 / 守护进程 ---------------- */
const WATCHDOG_PS1 = path.join(SCRIPTS, "watchdog.ps1");
const WATCHDOG_PID = path.join(ROOT, "data", "console", "watchdog.pid");
let healthInfo = null;

function fetchHealth() {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, { timeout: 1500 }, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch (e) {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => {
      req.destroy();
      resolve(null);
    });
  });
}

function watchdogRunning() {
  try {
    const pid = parseInt(String(fs.readFileSync(WATCHDOG_PID, "utf8")).trim(), 10);
    if (!pid) return false;
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return false;
  }
}

function ensureWatchdog() {
  if (watchdogRunning()) {
    shellLog("watchdog already running");
    return;
  }
  try {
    // 与 runScript 保持一致：用文件句柄接输出（detached + ignore 在部分环境会被静默杀掉）
    const outFd = fs.openSync(path.join(ROOT, "desktop", "watchdog.out.log"), "a");
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", WATCHDOG_PS1],
      { cwd: SCRIPTS, windowsHide: true, stdio: ["ignore", outFd, outFd] }
    );
    child.on("error", (err) => shellLog("watchdog spawn error: " + (err && err.message)));
    child.on("exit", (code) => shellLog("watchdog exit code=" + code));
    child.unref();
    shellLog("watchdog spawned pid=" + child.pid);
  } catch (e) {
    shellLog("watchdog spawn failed: " + (e && e.message));
  }
}

/** 托盘/菜单上显示的一句话状态 */
function statusLabel() {
  if (healthInfo) {
    if (!healthInfo.watchdog) return "状态未知（守护未运行）";
    if (healthInfo.verdict === "ok") {
      const who = healthInfo.qq && healthInfo.qq.nickname ? " · " + healthInfo.qq.nickname : "";
      return "全部正常" + who;
    }
    const bad = (healthInfo.components || [])
      .filter((c) => !c.ok)
      .map((c) => c.name)
      .join("、");
    return (healthInfo.verdict === "down" ? "服务不可用：" : "部分异常：") + (bad || "未知");
  }
  return servicesState === "running"
    ? "小鲸鱼：运行中"
    : servicesState === "starting"
    ? "小鲸鱼：启动中…"
    : "小鲸鱼：未运行";
}

/** 运行 scripts 下的 ps1；wait=true 时等它退出 */function runScript(name, wait = false) {
  return new Promise((resolve) => {
    const script = path.join(SCRIPTS, name);
    shellLog(`runScript ${name} wait=${wait} exists=${fs.existsSync(script)}`);
    const outFd = fs.openSync(path.join(ROOT, "desktop", "shell-script.out.log"), "a");
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
      { cwd: SCRIPTS, windowsHide: true, stdio: ["ignore", outFd, outFd] }
    );
    child.on("error", (err) => shellLog(`runScript ${name} spawn error: ${err && err.message}`));
    if (wait) {
      child.on("close", () => resolve());
      child.on("error", () => resolve());
    } else {
      child.on("exit", (code) => shellLog(`runScript ${name} exit code=${code}`));
      resolve();
    }
  });
}

function readSettings() {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROOT, "desktop", "settings.json"), "utf8"));
  } catch (e) {
    return {};
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/* ---------------- 小鲸鱼服务 ---------------- */
async function servicesUp() {
  const [a, b] = await Promise.all([portOpen(6185), portOpen(6099)]);
  return a && b;
}

async function ensureServices() {
  if (servicesState === "starting") {
    shellLog("ensureServices: already starting, skip");
    return;
  }
  if (await servicesUp()) {
    // 二次确认：可能是刚被 kill、端口还没释放的假健康状态
    await sleep(2200);
    if (await servicesUp()) {
      servicesState = "running";
      updateTray();
      return;
    }
    shellLog("ensureServices: 端口短暂存在后消失，按未启动处理");
  }
  shellLog("services not up, starting...");
  servicesState = "starting";
  updateTray();
  await runScript("start-qq-agent.ps1");
  for (let i = 0; i < 45; i++) {
    await sleep(2000);
    if (await servicesUp()) {
      shellLog("services up");
      servicesState = "running";
      updateTray();
      return;
    }
  }
  servicesState = "stopped";
  updateTray();
}

async function waitServicesDown(timeoutMs = 1500) {
  const ports = [6185, 6199, 6099, 8787];
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const checks = await Promise.all(ports.map((p) => portOpen(p)));
    if (!checks.some(Boolean)) return true;
    await sleep(150);
  }
  return false;
}

function fastStop() {
  return new Promise((resolve) => {
    const script = path.join(SCRIPTS, "fast-stop.ps1");
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    try {
      const child = spawn(
        "powershell.exe",
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
        { cwd: SCRIPTS, windowsHide: true, stdio: "ignore" }
      );
      child.on("close", finish);
      child.on("error", finish);
    } catch (e) {
      finish();
    }
    // 兜底：最多等 2 秒
    setTimeout(finish, 2000);
  });
}

async function stopServices() {
  await runScript("stop-qq-agent.ps1", true);
  servicesState = "stopped";
  updateTray();
}

/* ---------------- 控制台后端 ---------------- */
function ensureConsoleServer(cb) {
  let fired = false;
  const done = () => {
    if (fired) return;
    fired = true;
    cb();
  };
  pingConsole((ok) => {
    if (ok) return done();
    try {
      const p = spawn(PYTHONW, [SERVER], {
        cwd: path.join(ROOT, "console"),
        detached: true,
        stdio: "ignore",
        windowsHide: true,
      });
      p.unref();
    } catch (e) {
      /* 起不来也让窗口打开，页面里会提示 */
    }
    let tries = 0;
    const timer = setInterval(() => {
      pingConsole((up) => {
        if (up || ++tries > 15) {
          clearInterval(timer);
          done();
        }
      });
    }, 400);
  });
}

/* ---------------- 窗口 ---------------- */
function createWindow() {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 980,
    minHeight: 640,
    title: "小鲸鱼控制台",
    backgroundColor: "#090c13",
    autoHideMenuBar: true,
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#0b0f18",
      symbolColor: "#e6ebf5",
      height: 60,
    },
    icon: path.join(__dirname, "icon.png"),
    webPreferences: { contextIsolation: true, nodeIntegration: false, spellcheck: false },
  });

  mainWindow.loadURL(CONSOLE_URL);

  // 页面里的 window.open / target=_blank 统一交给系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  // 关窗行为：设置里是 tray 就隐藏到托盘，否则退出壳（服务都不停）
  mainWindow.on("close", (e) => {
    const action = readSettings().closeAction || "quit";
    if (action === "tray") {
      e.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on("closed", () => (mainWindow = null));
}

/* ---------------- 托盘 ---------------- */
function trayMenu() {
  return Menu.buildFromTemplate([
    {
      label: statusLabel(),
      enabled: false,
    },
    { type: "separator" },
    { label: "显示控制台", click: () => (mainWindow ? (mainWindow.show(), mainWindow.focus()) : createWindow()) },
    { label: "在浏览器打开", click: () => shell.openExternal(CONSOLE_URL) },
    { type: "separator" },
    { label: "启动小鲸鱼", click: () => ensureServices() },
    { label: "重启 AstrBot", click: () => runScript("restart-astrbot.ps1") },
    { label: "启动守护", click: () => ensureWatchdog() },
    { type: "separator" },
    {
      label: "退出",
      click: async () => {
        isQuitting = true;
        // 视觉上立刻关闭
        try {
          if (mainWindow) mainWindow.hide();
        } catch (e) {}
        try {
          if (tray) {
            tray.destroy();
            tray = null;
          }
        } catch (e) {}
        // 后台快速清理：等端口真正释放（最多 1.5 秒）再退出
        await fastStop();
        await waitServicesDown(1500);
        app.exit(0);
      },
    },
  ]);
}

function updateTray() {
  if (tray) {
    tray.setContextMenu(trayMenu());
    tray.setToolTip("小鲸鱼 · " + statusLabel());
  }
}

function createTray() {
  if (tray) return;
  try {
    const icon = nativeImage.createFromPath(path.join(__dirname, "icon.png"));
    tray = new Tray(icon.resize({ width: 16, height: 16 }));
    updateTray();
    tray.on("double-click", () => (mainWindow ? mainWindow.show() : createWindow()));
  } catch (e) {
    /* 托盘失败不影响主窗口 */
  }
}

/* ---------------- 生命周期 ---------------- */
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (isQuitting) return;
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    ensureConsoleServer(() => {
      createWindow();
      createTray();
      ensureWatchdog();
      // 健康状态：启动即查一次，之后每 15 秒刷新托盘
      fetchHealth().then((h) => {
        healthInfo = h;
        updateTray();
      });
      setInterval(async () => {
        if (isQuitting) return;
        healthInfo = await fetchHealth();
        updateTray();
      }, 15000);
      // 启动软件时自动启动小鲸鱼（不阻塞窗口）
      ensureServices();
    });

    // 看门狗：每 30 秒检查一次，服务掉线则自动拉起
    let lastHealthy = true;
    setInterval(async () => {
      if (isQuitting || servicesState === "starting") return;
      const up = await servicesUp();
      if (up) {
        lastHealthy = true;
          return;
      }
      if (lastHealthy) {
        shellLog("watchdog: 服务掉线，尝试自动拉起");
        servicesState = "unknown";
        updateTray();
        ensureServices();
        lastHealthy = false;
      }
    }, 30000);
  });

  app.on("before-quit", () => {
    isQuitting = true;
  });

  app.on("window-all-closed", () => {
    // 关窗 = 只退出外壳；小鲸鱼服务继续在后台跑
    if (process.platform !== "darwin") app.quit();
  });
}
