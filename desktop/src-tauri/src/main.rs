// thync on the desktop: a cloud that wanders the screen and shows what thync sees (ui/pet.js), a menu bar icon,
// and the usual thync page in its own window. The hub keeps running on its own, so the web page stays available.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Duration;

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_notification::NotificationExt;

const HUB: &str = "http://127.0.0.1:8765";

fn state_dir() -> PathBuf {
    std::env::var("THYNC_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".thync"))
}

fn token() -> Option<String> {
    std::fs::read_to_string(state_dir().join("token"))
        .ok()
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
}

/// The thync checkout this app was built from; used to start the hub when there is no ~/.thync/run.sh.
fn repo_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// What the cloud shows: GET /status.json from the hub. Done here, not in the page, so the token stays out of it.
#[tauri::command]
fn status() -> Result<serde_json::Value, String> {
    let token = token().ok_or("thync 토큰이 없어요")?;
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(3)).build();
    agent
        .get(&format!("{HUB}/status.json"))
        .set("X-Thync-Token", &token)
        .call()
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>()
        .map_err(|e| e.to_string())
}

fn show_main(app: &AppHandle) -> tauri::Result<()> {
    if let Some(w) = app.get_webview_window("main") {
        w.show()?;
        w.unminimize()?;
        return w.set_focus();
    }
    let url: tauri::Url = format!("{HUB}/#t={}", token().unwrap_or_default()).parse().expect("hub url");
    let w = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("thync")
        .inner_size(1400.0, 900.0)
        .build()?;
    w.set_focus()
}

#[tauri::command]
fn open_thync(app: AppHandle) -> Result<(), String> {
    show_main(&app).map_err(|e| e.to_string())
}

/// A macOS notification and a short sound, for a question waiting on me or a long run that just ended.
#[tauri::command]
fn notify(app: AppHandle, title: String, body: String) {
    let _ = app.notification().builder().title(title).body(body).show();
    let _ = Command::new("/usr/bin/afplay")
        .arg("/System/Library/Sounds/Glass.aiff")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

/// Start the hub in the background, through a login shell so it finds the same python3 and gh as the terminal.
/// ~/.thync/run.sh wins when it exists (it may pick a GitHub account); the hub outlives this app either way.
#[tauri::command]
fn start_hub() -> Result<(), String> {
    let run = state_dir().join("run.sh");
    let mut cmd = Command::new("/bin/zsh");
    if run.exists() {
        cmd.arg("-lc").arg("sh \"$0\"").arg(run);
    } else {
        let log = state_dir().join("server.log");
        cmd.arg("-lc")
            .arg("nohup python3 -u -m thync >> \"$0\" 2>&1 < /dev/null &")
            .arg(log)
            .current_dir(repo_dir());
    }
    cmd.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![status, open_thync, notify, start_hub])
        .setup(|app| {
            // Lives in the menu bar, not the Dock.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let open = MenuItem::with_id(app, "open", "thync 열기", true, None::<&str>)?;
            let toggle = MenuItem::with_id(app, "toggle", "구름 숨기기 / 보이기", true, None::<&str>)?;
            let hub = MenuItem::with_id(app, "hub", "허브 켜기", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "종료", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &toggle, &hub, &quit])?;
            TrayIconBuilder::with_id("tray")
                .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .tooltip("thync")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        let _ = show_main(app);
                    }
                    "toggle" => {
                        if let Some(w) = app.get_webview_window("pet") {
                            let _ = if w.is_visible().unwrap_or(true) { w.hide() } else { w.show() };
                        }
                    }
                    "hub" => {
                        let _ = start_hub();
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("thync desktop failed to start");
    app.run(|_, event| {
        // Closing the thync window or hiding the cloud keeps the app in the menu bar; only 종료 quits.
        if let RunEvent::ExitRequested { code: None, api, .. } = event {
            api.prevent_exit();
        }
    });
}
