// DFlow desktop shell.
//
// The app is the same agent (FastAPI, bundled with PyInstaller as
// resources/agent/dflow-agent.exe) and the same web UI it serves on
// http://127.0.0.1:8434 — this shell only:
//   * starts the agent in the background (no console window) with the app's
//     folders in its environment, restarts it when it asks to (exit code 75,
//     after a settings change) or crashes, and stops it (whole process tree)
//     when the app quits;
//   * shows a loading page (ui/index.html) that switches to the agent's UI
//     once it answers;
//   * keeps one instance, and keeps running in the tray when the window is
//     closed (scheduled posts need the agent alive);
//   * opens links that want a new window in the normal browser.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const AGENT_PORT: u16 = 8434;
/// The agent exits with this code to be started again (settings that need a restart).
const RESTART_CODE: i32 = 75;
/// Crashes restarted automatically before giving up (the loading page then shows the log path).
const MAX_CRASH_RESTARTS: u32 = 3;

struct Agent {
    child: Mutex<Option<Child>>,
    quitting: AtomicBool,
}

/// A drive needs this much free space to hold the app's data (pictures, videos, the WebView cache).
const MIN_FREE_BYTES: u64 = 5 * 1024 * 1024 * 1024;

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn GetDriveTypeW(root: *const u16) -> u32;
    fn GetDiskFreeSpaceExW(dir: *const u16, avail: *mut u64, total: *mut u64, free: *mut u64) -> i32;
}

/// The first fixed drive other than C: with room to spare (D:, E:…), as `X:\`.
#[cfg(windows)]
fn roomy_data_drive() -> Option<PathBuf> {
    const DRIVE_FIXED: u32 = 3;
    for letter in b'D'..=b'Z' {
        let root = format!("{}:\\", letter as char);
        let wide: Vec<u16> = root.encode_utf16().chain(std::iter::once(0)).collect();
        // SAFETY: `wide` is a NUL-terminated UTF-16 path that outlives both calls; the out-pointers are valid u64s.
        let (kind, ok, avail) = unsafe {
            let kind = GetDriveTypeW(wide.as_ptr());
            let (mut avail, mut total, mut free) = (0u64, 0u64, 0u64);
            let ok = GetDiskFreeSpaceExW(wide.as_ptr(), &mut avail, &mut total, &mut free);
            (kind, ok, avail)
        };
        if kind == DRIVE_FIXED && ok != 0 && avail >= MIN_FREE_BYTES {
            return Some(PathBuf::from(root));
        }
    }
    None
}

#[cfg(not(windows))]
fn roomy_data_drive() -> Option<PathBuf> {
    None
}

fn writable(dir: &std::path::Path) -> bool {
    if std::fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".dflow-write-test");
    let ok = std::fs::write(&probe, b"ok").is_ok();
    let _ = std::fs::remove_file(&probe);
    ok
}

/// Where the app keeps its settings (.env), logs, data and WebView cache — kept OFF drive C when the machine has
/// another fixed drive with room (C is usually the small one): `X:\DFlowData` on the first such drive, else
/// `%LOCALAPPDATA%\DFlowData`. Picked once and remembered in `%APPDATA%\vn.dflow.desktop\home.txt` (so a later
/// USB disk or a fuller D: never moves it); never the install folder, so an update / uninstall leaves it alone.
fn dflow_home(app: &AppHandle) -> PathBuf {
    let fallback = app
        .path()
        .local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir())
        .join("DFlowData");
    let pointer = app.path().app_config_dir().ok().map(|d| d.join("home.txt"));
    if let Some(saved) = pointer.as_ref().and_then(|p| std::fs::read_to_string(p).ok()) {
        let saved = PathBuf::from(saved.trim());
        if !saved.as_os_str().is_empty() && writable(&saved) {
            return saved;
        }
    }
    let chosen = roomy_data_drive()
        .map(|root| root.join("DFlowData"))
        .filter(|dir| writable(dir))
        .unwrap_or(fallback);
    if let Some(p) = pointer {
        if let Some(parent) = p.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&p, chosen.to_string_lossy().as_bytes());
    }
    chosen
}

/// A string as a JavaScript literal (the log path for the loading page).
fn js_string(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn hidden(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

fn agent_answers() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], AGENT_PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn spawn_agent(app: &AppHandle) -> std::io::Result<Child> {
    let res = app
        .path()
        .resource_dir()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::NotFound, e.to_string()))?;
    let home = dflow_home(app);
    std::fs::create_dir_all(home.join("logs"))?;
    let exe = res.join("agent").join("dflow-agent.exe");
    // ffmpeg / ffprobe ship with the app; whatever the user installed (yt-dlp, claude…) stays reachable after them.
    let path = std::env::var_os("PATH").unwrap_or_default();
    let paths = std::iter::once(res.join("ffmpeg")).chain(std::env::split_paths(&path));
    let path = std::env::join_paths(paths).unwrap_or(path);
    let mut cmd = Command::new(exe);
    cmd.env("FLOWBOARD_APP", "1")
        .env("FLOWBOARD_HOME", &home)
        .env("FLOWBOARD_WEB_DIR", res.join("web"))
        .env("FLOWBOARD_EXTENSION_DIR", res.join("extension"))
        .env("FLOWBOARD_PARENT_PID", std::process::id().to_string())
        .env("PATH", path)
        .current_dir(&home)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hidden(&mut cmd).spawn()
}

fn kill_tree(child: &mut Child) {
    // the agent starts ffmpeg / node / the dubbing runner: stop them with it
    let pid = child.id().to_string();
    let _ = hidden(Command::new("taskkill").args(["/PID", &pid, "/T", "/F"])).status();
    let _ = child.kill();
    let _ = child.wait();
}

fn stop_agent(app: &AppHandle) {
    let state = app.state::<Agent>();
    state.quitting.store(true, Ordering::SeqCst);
    // take the child out first: the lock guard must not outlive `state`
    let child = state.child.lock().ok().and_then(|mut guard| guard.take());
    if let Some(mut child) = child {
        kill_tree(&mut child);
    }
}

/// Starts the agent (unless one already answers on its port — a DFlow started by hand, say) and keeps
/// it alive: restarted when it asks to (exit code 75) or crashes, at most MAX_CRASH_RESTARTS times in a row.
fn watch_agent(app: AppHandle) {
    std::thread::spawn(move || {
        if !agent_answers() {
            let first = spawn_agent(&app).ok();
            *app.state::<Agent>().child.lock().unwrap() = first;
        }
        let mut crashes = 0u32;
        let mut started = Instant::now();
        loop {
            std::thread::sleep(Duration::from_millis(700));
            let state = app.state::<Agent>();
            if state.quitting.load(Ordering::SeqCst) {
                break;
            }
            let mut guard = match state.child.lock() {
                Ok(g) => g,
                Err(_) => break,
            };
            let exited = match guard.as_mut() {
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => Some(status.code()),
                    _ => None,
                },
                None => None,
            };
            let Some(code) = exited else { continue };
            *guard = None;
            if code == Some(RESTART_CODE) {
                crashes = 0;
            } else {
                if started.elapsed() > Duration::from_secs(120) {
                    crashes = 0; // it ran fine for a while: count this crash afresh
                }
                crashes += 1;
                if crashes > MAX_CRASH_RESTARTS {
                    break;
                }
            }
            started = Instant::now();
            *guard = spawn_agent(&app).ok();
        }
    });
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn open_external(target: &str) {
    let _ = hidden(Command::new("explorer").arg(target)).spawn();
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // a second launch only brings the running one forward
            show_main(app);
        }))
        .manage(Agent { child: Mutex::new(None), quitting: AtomicBool::new(false) })
        .setup(|app| {
            let handle = app.handle().clone();
            let home = dflow_home(&handle);
            watch_agent(handle.clone());

            let nav = handle.clone();
            let log_path = home.join("logs").join("agent.log");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("DFlow")
                // the WebView2 profile (cookies, cache) next to the data, off drive C as well
                .data_directory(home.join("webview"))
                .initialization_script(&format!("window.__DFLOW_LOG__ = {};", js_string(&log_path.to_string_lossy())))
                .inner_size(1440.0, 900.0)
                .min_inner_size(1024.0, 640.0)
                .maximized(true)
                .on_new_window(move |url, _features| {
                    // the app's own pages stay in the window; everything else (Facebook, Flow, Muse…) goes to the browser
                    let own = url.host_str() == Some("127.0.0.1") && url.port() == Some(AGENT_PORT);
                    if own {
                        if let Some(w) = nav.get_webview_window("main") {
                            let _ = w.navigate(url);
                        }
                    } else {
                        open_external(url.as_str());
                    }
                    NewWindowResponse::Deny
                })
                .build()?;

            let open = MenuItem::with_id(app, "open", "Mở DFlow", true, None::<&str>)?;
            let folder = MenuItem::with_id(app, "folder", "Mở thư mục dữ liệu", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Thoát DFlow", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &folder, &quit])?;
            let mut tray = TrayIconBuilder::with_id("dflow")
                .tooltip("DFlow — đang chạy (lịch đăng vẫn hoạt động khi đóng cửa sổ)")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => show_main(app),
                    "folder" => open_external(&dflow_home(app).to_string_lossy()),
                    "quit" => {
                        stop_agent(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        show_main(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // closing the window keeps DFlow in the tray: the agent goes on (auto posts, renders)
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building DFlow");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_agent(handle);
        }
    });
}
