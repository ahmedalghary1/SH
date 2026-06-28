const { app, BrowserWindow, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const HOST = '127.0.0.1';
const PORT = Number(process.env.APP_PORT || 8765);
const START_URL = `http://${HOST}:${PORT}/desktop-sync/`;

let backendProcess = null;
let mainWindow = null;
let mainLogStream = null;

function appLogPath() {
  return path.join(app.getPath('userData'), 'electron.log');
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  if (!mainLogStream) {
    fs.mkdirSync(app.getPath('userData'), { recursive: true });
    mainLogStream = fs.createWriteStream(appLogPath(), { flags: 'a' });
  }
  mainLogStream.write(line);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function statusHtml(title, detail = '') {
  return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SH Desktop</title>
  <style>
    body { margin: 0; font-family: Tahoma, Arial, sans-serif; background: #f8fafc; color: #111827; }
    main { min-height: 100vh; display: grid; place-items: center; padding: 32px; box-sizing: border-box; }
    section { width: min(560px, 100%); background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 24px; box-shadow: 0 10px 30px rgba(15, 23, 42, .08); }
    h1 { margin: 0 0 12px; font-size: 22px; }
    p { margin: 0; line-height: 1.7; color: #4b5563; white-space: pre-wrap; direction: ltr; text-align: left; }
    .brand { direction: rtl; text-align: right; color: #111827; }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>${escapeHtml(title)}</h1>
      <p class="brand">يرجى الانتظار أثناء تشغيل قاعدة البيانات المحلية وخادم التطبيق.</p>
      ${detail ? `<p>${escapeHtml(detail)}</p>` : ''}
    </section>
  </main>
</body>
</html>`;
}

function backendExecutable() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend-dist', 'SHDesktopBackend', 'SHDesktopBackend.exe');
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function backendArgs() {
  if (app.isPackaged) {
    return ['--host', HOST, '--port', String(PORT)];
  }
  return [path.join(__dirname, '..', 'run_app.py'), '--host', HOST, '--port', String(PORT)];
}

function waitForPort(timeoutMs = 45000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const socket = net.createConnection({ host: HOST, port: PORT }, () => {
        socket.destroy();
        resolve();
      });
      socket.on('error', () => {
        socket.destroy();
        if (Date.now() - started > timeoutMs) {
          reject(new Error('Django backend did not start in time.'));
          return;
        }
        setTimeout(check, 500);
      });
    };
    check();
  });
}

function startBackend() {
  const env = {
    ...process.env,
    APP_HOST: HOST,
    APP_PORT: String(PORT),
    DESKTOP_LOCAL_MODE: '1',
    DESKTOP_SYNC_AUTOSTART: '1'
  };
  delete env.ELECTRON_RUN_AS_NODE;

  const executable = backendExecutable();
  if (!fs.existsSync(executable) && app.isPackaged) {
    throw new Error(`Backend executable was not found: ${executable}`);
  }

  const logPath = path.join(app.getPath('userData'), 'backend.log');
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  const logStream = fs.createWriteStream(logPath, { flags: 'a' });
  log(`Starting backend: ${executable} ${backendArgs().join(' ')}`);
  backendProcess = spawn(backendExecutable(), backendArgs(), {
    cwd: app.isPackaged ? process.resourcesPath : path.join(__dirname, '..'),
    env,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  backendProcess.stdout.on('data', (chunk) => logStream.write(chunk));
  backendProcess.stderr.on('data', (chunk) => logStream.write(chunk));
  backendProcess.on('error', (error) => {
    log(`Backend spawn error: ${error.stack || error.message}`);
  });
  backendProcess.on('exit', (code, signal) => {
    log(`Backend exited: code=${code} signal=${signal || ''}`);
    logStream.end();
    backendProcess = null;
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 700,
    title: 'SH Desktop',
    backgroundColor: '#f8fafc',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    log(`Renderer failed to load ${validatedURL}: ${errorCode} ${errorDescription}`);
    mainWindow.loadURL(
      'data:text/html;charset=utf-8,' +
        encodeURIComponent(statusHtml('تعذر فتح التطبيق', `${errorDescription}\n${validatedURL}`))
    );
  });
  await mainWindow.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent(statusHtml('جار تشغيل SH Desktop'))
  );
}

app.whenReady().then(async () => {
  try {
    await createWindow();
    startBackend();
    await waitForPort();
    log(`Backend port is ready: ${START_URL}`);
    await mainWindow.loadURL(START_URL);
  } catch (error) {
    log(`Startup error: ${error.stack || error.message}`);
    if (mainWindow) {
      await mainWindow.loadURL(
        'data:text/html;charset=utf-8,' +
          encodeURIComponent(statusHtml('تعذر تشغيل التطبيق', error.stack || error.message))
      );
    } else {
      dialog.showErrorBox('SH Desktop', error.message);
      app.quit();
    }
  }
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
  if (mainLogStream) {
    mainLogStream.end();
  }
});
